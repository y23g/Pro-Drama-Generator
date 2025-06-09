import gradio as gr
import requests
import os
from datetime import datetime
from fpdf import FPDF
import tempfile
import re
import json
import base64
from PIL import Image
import io

# API 配置
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# 千帆ERNIE IRAG API配置
QIANFAN_API_KEY = os.getenv("QIANFAN_API_KEY")
QIANFAN_IMAGE_URL = "https://qianfan.baidubce.com/v2/images/generations"

# 角色档案模板
ROLE_TEMPLATE = """
{name} ({role_type}):
- 年龄: {age}
- 外貌: {appearance}
- 性格: {personality}
- 背景故事: {background_story}
- 习惯/特点: {habits}
- 与其他角色关系: {relationships}
"""

# 剧本生成提示词模板
PROMPT_TEMPLATE = """
你是一个经验丰富的剧本编剧助手。请根据以下设定，生成一段剧本片段：

标题: {title}
角色档案: 
{roles}
风格: {style}
背景设定: {background}
初始剧情: {prompt}

要求：输出剧本格式，包含角色对话，环境描写，适当添加情绪提示词。
{length_instruction}
"""


class CharacterManager:
    def __init__(self):
        self.characters = []
        self.load_characters()

    def load_characters(self):
        """加载角色档案"""
        try:
            if os.path.exists("characters.json"):
                with open("characters.json", "r", encoding="utf-8") as f:
                    self.characters = json.load(f)
                    # 为旧数据添加图片字段
                    for char in self.characters:
                        if 'avatar_image' not in char:
                            char['avatar_image'] = None
                print(f"✅ 成功加载角色档案，数量: {len(self.characters)}")
                print(f"📋 角色列表: {[char['name'] for char in self.characters]}")
            else:
                print("📁 角色档案文件不存在，创建新的空档案")
        except Exception as e:
            print(f"❌ 加载角色档案失败: {str(e)}")

    def save_characters(self):
        """保存角色档案"""
        try:
            with open("characters.json", "w", encoding="utf-8") as f:
                json.dump(self.characters, f, ensure_ascii=False, indent=2)
            print(f"💾 角色档案已保存，数量: {len(self.characters)}")
            print(f"📋 保存的角色: {[char['name'] for char in self.characters]}")
        except Exception as e:
            print(f"❌ 保存角色档案失败: {str(e)}")

    def add_character(self, character_data):
        """添加角色"""
        character_data['avatar_image'] = None
        self.characters.append(character_data)
        self.save_characters()
        print(f"➕ 角色已添加: {character_data['name']}, 当前角色数量: {len(self.characters)}")

    def update_character(self, index, character_data):
        """更新角色"""
        if 0 <= index < len(self.characters):
            # 保留原有图片
            if 'avatar_image' in self.characters[index]:
                character_data['avatar_image'] = self.characters[index]['avatar_image']
            else:
                character_data['avatar_image'] = None
            old_name = self.characters[index]['name']
            self.characters[index] = character_data
            self.save_characters()
            print(f"✏️ 角色已更新: {old_name} -> {character_data['name']}")

    def update_character_image(self, index, image_data):
        """更新角色图片"""
        if 0 <= index < len(self.characters):
            self.characters[index]['avatar_image'] = image_data
            self.save_characters()
            print(f"🎨 角色头像已更新: {self.characters[index]['name']}")

    def delete_character(self, index):
        """删除角色"""
        if 0 <= index < len(self.characters):
            deleted_name = self.characters[index]['name']
            del self.characters[index]
            self.save_characters()
            print(f"🗑️ 角色已删除: {deleted_name}, 剩余角色数量: {len(self.characters)}")

    def get_dropdown_choices(self):
        """获取下拉菜单选项"""
        choices = [f"{i}: {char['name']} ({char['role_type']})" for i, char in enumerate(self.characters)]
        print(f"🔄 生成角色选项: {choices}")
        return choices

    def format_roles_for_prompt(self, selected_indices):
        """格式化角色信息用于prompt"""
        formatted_roles = []
        for idx in selected_indices:
            try:
                char_index = int(idx.split(":")[0])
                if 0 <= char_index < len(self.characters):
                    char = self.characters[char_index]
                    formatted_roles.append(ROLE_TEMPLATE.format(**char))
            except (ValueError, IndexError):
                continue
        return "\n".join(formatted_roles)

    def character_exists(self, name, role_type):
        """检查角色是否存在"""
        return any(char['name'].strip().lower() == name.strip().lower() and
                   char['role_type'].strip().lower() == role_type.strip().lower()
                   for char in self.characters)


# 图片生成相关函数
def generate_character_prompt(character_data):
    """根据角色档案生成中文图片描述prompt"""
    name = character_data.get('name', '')
    age = character_data.get('age', '')
    appearance = character_data.get('appearance', '')
    personality = character_data.get('personality', '')
    role_type = character_data.get('role_type', '')

    # 构建中文prompt
    prompt_parts = []

    # 基础描述
    if age:
        prompt_parts.append(f"{age}岁")

    if role_type:
        prompt_parts.append(f"{role_type}")

    if appearance:
        prompt_parts.append(f"外貌：{appearance}")

    if personality:
        prompt_parts.append(f"性格：{personality}")

    # 添加艺术风格
    prompt_parts.append("高质量人物肖像，数字艺术风格，细节丰富，专业摄影")

    prompt = f"{name}的角色肖像，" + "，".join(prompt_parts)

    # 限制prompt长度（API要求不超过220字符）
    if len(prompt) > 200:
        prompt = prompt[:200] + "..."

    return prompt


def call_qianfan_image_api(prompt):
    """调用千帆ERNIE IRAG API生成图片"""
    if not QIANFAN_API_KEY:
        return None, "未配置千帆API密钥，请在环境变量中设置 QIANFAN_API_KEY"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {QIANFAN_API_KEY}"
    }

    data = {
        "model": "irag-1.0",
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",  # 适合头像的尺寸
    }

    try:
        response = requests.post(QIANFAN_IMAGE_URL, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()

        if result.get("data") and len(result["data"]) > 0:
            image_url = result["data"][0]["url"]

            # 下载图片并转换为base64
            img_response = requests.get(image_url, timeout=30)
            img_response.raise_for_status()
            image_base64 = base64.b64encode(img_response.content).decode()

            return image_base64, "图片生成成功！"
        else:
            return None, "API返回数据异常，请检查prompt内容"

    except requests.exceptions.RequestException as e:
        return None, f"网络请求失败：{str(e)}"
    except json.JSONDecodeError as e:
        return None, f"API响应格式错误：{str(e)}"
    except Exception as e:
        return None, f"调用千帆API出错：{str(e)}"


def generate_character_image(character_index):
    """生成角色图片的主函数"""
    if character_index == -1:
        return None, "请先选择角色"

    if character_index >= len(character_manager.characters):
        return None, "角色索引无效"

    character_data = character_manager.characters[character_index]
    prompt = generate_character_prompt(character_data)

    print(f"🎨 生成图片的prompt: {prompt}")  # 调试信息

    image_data, message = call_qianfan_image_api(prompt)

    if image_data:
        # 保存图片到角色档案
        character_manager.update_character_image(character_index, image_data)
        # 转换为PIL Image对象供Gradio显示
        try:
            image_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(image_bytes))
            return image, message
        except Exception as e:
            return None, f"图片处理失败：{str(e)}"

    return None, message


def get_character_image(character_index):
    """获取角色的已有图片"""
    if character_index == -1 or character_index >= len(character_manager.characters):
        return None

    character = character_manager.characters[character_index]
    if character.get('avatar_image'):
        try:
            image_bytes = base64.b64decode(character['avatar_image'])
            image = Image.open(io.BytesIO(image_bytes))
            return image
        except Exception as e:
            print(f"加载角色图片失败: {str(e)}")

    return None


# 剧本生成相关函数
def count_words(text):
    """统计中文字符数（排除标点符号）"""
    if not text:
        return 0
    chinese_chars = re.findall(r'[\u4e00-\u9fa5]', text)
    return len(chinese_chars)


def call_deepseek_api(prompt, temperature=0.9):
    """调用DeepSeek API"""
    if not DEEPSEEK_API_KEY:
        return "错误：未配置 DeepSeek API 密钥。"

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个中文剧本创作专家。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": float(temperature),
        "max_tokens": 4000
    }

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"调用 DeepSeek API 出错：{str(e)}"


def adjust_script_length(script, word_limit):
    """调整剧本长度"""
    if not word_limit:
        return script

    current_words = count_words(script)
    target_min, target_max = int(word_limit), int(word_limit) + 100

    if current_words < target_min:
        prompt = f"请将以下剧本扩充到{target_min}-{target_max}字(仅统计中文字符)，保持内容连贯:\n{script}"
        expanded_script = call_deepseek_api(prompt, 0.7)
        return expanded_script if "出错" not in expanded_script else script

    elif current_words > target_max:
        sentences = re.split(r'(?<=[。！？])', script)
        new_script = ""
        char_count = 0

        for sentence in sentences:
            sentence_words = count_words(sentence)
            if char_count + sentence_words > target_max:
                break
            new_script += sentence
            char_count += sentence_words

        return new_script.strip()

    return script


def generate_script(title, selected_chars, manual_roles, style, background, prompt, tone, temperature, word_limit,
                    append=False):
    """生成剧本主函数"""
    length_instruction = (
        f"请将剧本片段控制在 **{word_limit} 到 {int(word_limit) + 100} 字之间**（仅统计中文字符）。"
        f"内容不要超出限制，避免重复或冗长描述。"
    ) if word_limit else ""

    formatted_roles = character_manager.format_roles_for_prompt(selected_chars)
    if manual_roles:
        if formatted_roles:
            formatted_roles += "\n\n手动添加角色:\n" + manual_roles
        else:
            formatted_roles = "手动添加角色:\n" + manual_roles

    if append:
        full_prompt = f"请继续续写上一段剧本，保持情节连贯：\n{prompt}\n\n{length_instruction}"
    else:
        full_prompt = PROMPT_TEMPLATE.format(
            title=title, roles=formatted_roles, style=style,
            background=background, prompt=prompt, length_instruction=length_instruction
        )
        if tone:
            full_prompt += f"\n风格语气要求：{tone}"

    script = call_deepseek_api(full_prompt, temperature)
    return adjust_script_length(script, word_limit) if word_limit else script


def clean_text_for_pdf(text):
    """改进的文本清理函数，更好地处理中文字符"""
    if not text:
        return ""

    try:
        print("🧹 开始改进的文本清理...")

        # 1. 首先替换标点符号
        punctuation_map = {
            '：': ': ', '，': ', ', '。': '. ', '？': '? ', '！': '! ',
            '（': '(', '）': ')', '【': '[', '】': ']', '『': '[', '』': ']',
            '"': '"', '"': '"', ''': "'", ''': "'",
            '—': '-', '–': '-', '…': '...', '、': ', ',
            '；': '; ', '｜': '|', '〈': '<', '〉': '>',
            '《': '<', '》': '>', '「': '[', '」': ']'
        }

        cleaned_text = text
        for chinese_punct, english_punct in punctuation_map.items():
            cleaned_text = cleaned_text.replace(chinese_punct, english_punct)

        # 2. 扩展的中文词汇映射表
        chinese_words = {
            # 基础词汇
            '的': 'de', '了': 'le', '在': 'zai', '是': 'shi', '我': 'wo', '有': 'you', '和': 'he', '就': 'jiu',
            '不': 'bu', '人': 'ren', '都': 'dou', '一': 'yi', '个': 'ge', '上': 'shang', '也': 'ye', '很': 'hen',
            '到': 'dao', '说': 'shuo', '要': 'yao', '去': 'qu', '你': 'ni', '会': 'hui', '着': 'zhe', '没': 'mei',
            '看': 'kan', '好': 'hao', '自': 'zi', '己': 'ji', '面': 'mian', '前': 'qian', '最': 'zui', '新': 'xin',

            # 人称代词
            '他': 'ta', '她': 'ta', '它': 'ta', '们': 'men', '这': 'zhe', '那': 'na', '什': 'shen', '么': 'me',
            '哪': 'na', '里': 'li', '怎': 'zen', '样': 'yang', '多': 'duo', '少': 'shao', '几': 'ji',

            # 动词
            '来': 'lai', '走': 'zou', '跑': 'pao', '飞': 'fei', '游': 'you', '坐': 'zuo', '站': 'zhan', '躺': 'tang',
            '吃': 'chi', '喝': 'he', '睡': 'shui', '醒': 'xing', '想': 'xiang', '知': 'zhi', '道': 'dao', '听': 'ting',
            '做': 'zuo', '给': 'gei', '拿': 'na', '放': 'fang', '开': 'kai', '关': 'guan', '买': 'mai', '卖': 'mai',
            '找': 'zhao', '等': 'deng', '帮': 'bang', '打': 'da', '写': 'xie', '读': 'du', '学': 'xue', '教': 'jiao',

            # 形容词
            '大': 'da', '小': 'xiao', '高': 'gao', '低': 'di', '长': 'chang', '短': 'duan', '宽': 'kuan', '窄': 'zhai',
            '快': 'kuai', '慢': 'man', '早': 'zao', '晚': 'wan', '新': 'xin', '旧': 'jiu', '年': 'nian', '轻': 'qing',
            '美': 'mei', '丑': 'chou', '胖': 'pang', '瘦': 'shou', '强': 'qiang', '弱': 'ruo', '聪': 'cong',
            '明': 'ming',

            # 方位词
            '东': 'dong', '南': 'nan', '西': 'xi', '北': 'bei', '中': 'zhong', '内': 'nei', '外': 'wai',
            '左': 'zuo', '右': 'you', '后': 'hou', '旁': 'pang', '边': 'bian', '间': 'jian', '处': 'chu',

            # 时间词
            '年': 'nian', '月': 'yue', '日': 'ri', '天': 'tian', '时': 'shi', '分': 'fen', '秒': 'miao',
            '今': 'jin', '明': 'ming', '昨': 'zuo', '现': 'xian', '过': 'guo', '将': 'jiang', '未': 'wei',
            '春': 'chun', '夏': 'xia', '秋': 'qiu', '冬': 'dong', '早': 'zao', '午': 'wu', '晚': 'wan', '夜': 'ye',

            # 地点词
            '家': 'jia', '校': 'xiao', '园': 'yuan', '公': 'gong', '司': 'si', '店': 'dian', '场': 'chang',
            '路': 'lu', '街': 'jie', '桥': 'qiao', '山': 'shan', '水': 'shui', '河': 'he', '海': 'hai',
            '城': 'cheng', '市': 'shi', '镇': 'zhen', '村': 'cun', '国': 'guo', '省': 'sheng', '县': 'xian',

            # 剧本相关词汇
            '剧': 'ju', '本': 'ben', '角': 'jue', '色': 'se', '演': 'yan', '员': 'yuan', '导': 'dao', '演': 'yan',
            '编': 'bian', '剧': 'ju', '制': 'zhi', '片': 'pian', '电': 'dian', '影': 'ying', '视': 'shi', '频': 'pin',
            '舞': 'wu', '台': 'tai', '话': 'hua', '剧': 'ju', '音': 'yin', '乐': 'yue', '歌': 'ge', '舞': 'wu',

            # 情感词
            '爱': 'ai', '恨': 'hen', '喜': 'xi', '欢': 'huan', '怒': 'nu', '哀': 'ai', '乐': 'le',
            '高': 'gao', '兴': 'xing', '伤': 'shang', '心': 'xin', '害': 'hai', '怕': 'pa', '担': 'dan', '心': 'xin',
            '紧': 'jin', '张': 'zhang', '放': 'fang', '松': 'song', '平': 'ping', '静': 'jing', '激': 'ji',
            '动': 'dong',

            # 常用组合词
            '什么': 'shenme', '怎么': 'zenme', '为什么': 'weishenme', '那么': 'name', '这么': 'zheme',
            '不过': 'buguo', '但是': 'danshi', '然而': 'ranér', '因为': 'yinwei', '所以': 'suoyi',
            '如果': 'ruguo', '要是': 'yaoshi', '虽然': 'suiran', '虽说': 'suishuo', '尽管': 'jinguan',
            '可能': 'keneng', '也许': 'yexu', '大概': 'dagai', '应该': 'yinggai', '必须': 'bixu',
            '已经': 'yijing', '正在': 'zhengzai', '刚才': 'gangcai', '现在': 'xianzai', '以后': 'yihou',
            '学校': 'xuexiao', '老师': 'laoshi', '学生': 'xuesheng', '同学': 'tongxue', '朋友': 'pengyou',
            '家人': 'jiaren', '父亲': 'fuqin', '母亲': 'muqin', '儿子': 'erzi', '女儿': 'nüer',
            '哥哥': 'gege', '姐姐': 'jiejie', '弟弟': 'didi', '妹妹': 'meimei', '爷爷': 'yeye', '奶奶': 'nainai',
        }

        # 3. 按长度排序替换（先替换长词，避免被短词误替换）
        sorted_words = sorted(chinese_words.items(), key=lambda x: len(x[0]), reverse=True)
        for chinese, pinyin in sorted_words:
            cleaned_text = cleaned_text.replace(chinese, pinyin)

        # 4. 处理剩余的中文字符 - 使用更智能的方法
        final_text = ""
        for char in cleaned_text:
            if ord(char) <= 255:  # ASCII和Latin-1范围内的字符
                final_text += char
            elif char.isspace():  # 保留所有空白字符
                final_text += char
            elif '\u4e00' <= char <= '\u9fff':  # 中文字符范围
                # 对于未映射的中文字符，使用更友好的替换
                final_text += "[CN]"  # 标记为中文字符
            else:
                final_text += "?"  # 其他特殊字符

        # 5. 清理多余的标记和空格
        final_text = re.sub(r'\[CN\]\[CN\]+', '[CN]', final_text)  # 合并连续的中文标记
        final_text = re.sub(r'\s+', ' ', final_text)  # 合并多个空格
        final_text = final_text.strip()

        print(f"✅ 改进文本清理完成: {len(text)} -> {len(final_text)} 字符")
        print(f"📊 处理结果预览: {final_text[:100]}{'...' if len(final_text) > 100 else ''}")

        return final_text

    except Exception as e:
        print(f"❌ 文本清理失败: {e}")
        # 最安全的备用方案 - 只保留ASCII字符
        safe_text = ''.join(c if ord(c) < 128 else '[?]' for c in text)
        return safe_text


def create_enhanced_text_export(text):
    """创建增强的文本文件导出"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"script_export_{timestamp}.txt"

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='w', encoding='utf-8')

        # 创建美观的文本格式
        header = f"""
{'=' * 60}
🎭 剧本导出 / Script Export
{'=' * 60}
📅 导出时间: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}
📊 内容字数: {count_words(text)} 字 (仅中文字符)
📄 格式说明: UTF-8编码，完全保留中文字符
{'=' * 60}

"""

        footer = f"""

{'=' * 60}
✅ 导出完成 / Export Complete
📝 文件格式: UTF-8 纯文本
💡 建议使用: 记事本、VS Code、或任何支持UTF-8的文本编辑器打开
📧 问题反馈: yuntongxu7@gmail.com
{'=' * 60}
"""

        # 写入文件
        temp_file.write(header)
        temp_file.write(text)
        temp_file.write(footer)
        temp_file.close()

        file_size = os.path.getsize(temp_file.name)
        print(f"✅ 增强文本文件创建成功: {temp_file.name}, 大小: {file_size} bytes")

        return temp_file.name

    except Exception as e:
        print(f"❌ 增强文本导出失败: {e}")
        return None


def export_with_smart_format(text):
    """智能格式导出 - 优先文本，备用PDF"""
    if not text or not text.strip():
        return None, gr.update(value="❌ 没有内容可导出，请先生成剧本内容", visible=True)

    try:
        print("📄 开始智能格式导出...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        word_count = count_words(text)

        # 优先尝试创建UTF-8文本文件（完美支持中文）
        text_file = create_enhanced_text_export(text)
        if text_file and os.path.exists(text_file):
            file_size = os.path.getsize(text_file)
            success_msg = f"""✅ 文本格式导出成功！
📁 文件类型: UTF-8 纯文本文件 (.txt)
📊 文件大小: {file_size:,} 字节
📝 内容字数: {word_count} 字 (中文字符)
🕒 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
💡 优势: 完美支持中文显示，文件小，兼容性好

🔧 使用建议:
• Windows: 记事本、写字板
• Mac: TextEdit、预览
• 跨平台: VS Code、Sublime Text
• 手机: 任何文本阅读器"""

            return gr.update(value=text_file, visible=True), gr.update(value=success_msg, visible=True)

        # 文本导出失败时的备用处理
        return None, gr.update(value="❌ 文本导出失败，请检查系统权限", visible=True)

    except Exception as e:
        print(f"❌ 智能导出完全失败: {e}")
        error_msg = f"""❌ 导出过程出现错误
🐛 错误信息: {str(e)[:100]}...
💡 建议解决方案:
1. 检查系统磁盘空间是否充足
2. 确认应用有文件写入权限
3. 尝试复制文本内容手动保存
4. 联系技术支持: yuntongxu7@gmail.com"""

        return None, gr.update(value=error_msg, visible=True)


def export_pdf_as_backup(text):
    """PDF导出作为备用方案"""
    print("📄 尝试PDF备用导出...")
    return export_pdf_with_status(text)


def export_pdf_with_status(text):
    """增强的PDF导出功能，返回文件和状态信息"""
    if not text or not text.strip():
        return None, gr.update(value="❌ 没有内容可导出", visible=True)

    try:
        print("🔄 开始PDF导出...")

        # 关键步骤：预处理文本
        safe_text = clean_text_for_pdf(text)

        # 创建PDF
        pdf = FPDF()
        pdf.add_page()

        # 检查字体文件
        font_loaded = False
        if os.path.exists('simhei.ttf'):
            try:
                file_size = os.path.getsize('simhei.ttf')
                print(f"📁 发现simhei.ttf，大小: {file_size} bytes")

                # 检查是否为Git LFS指针文件
                if file_size > 1000000:  # 大于1MB才可能是真实字体
                    with open('simhei.ttf', 'rb') as f:
                        header = f.read(100)
                        if b'version https://git-lfs.github.com' not in header:
                            pdf.add_font('SimHei', '', 'simhei.ttf', uni=True)
                            pdf.set_font('SimHei', '', 10)
                            font_loaded = True
                            print("✅ SimHei字体加载成功")
                        else:
                            print("⚠️ 检测到Git LFS指针文件")
                else:
                    print("⚠️ 字体文件太小，可能是指针文件")
            except Exception as e:
                print(f"❌ 字体加载失败: {e}")

        # 如果中文字体失败，使用Arial
        if not font_loaded:
            print("🔤 使用ASCII模式，中文字符将被转换")
            pdf.set_font('Arial', '', 10)

        # 添加标题
        try:
            title_text = "Script Export (中文字符已转换)" if not font_loaded else "剧本导出"
            pdf.cell(0, 10, title_text, ln=True, align='C')
        except:
            pdf.cell(0, 10, "Script Export", ln=True, align='C')

        pdf.ln(5)

        # 添加说明（如果是转换模式）
        if not font_loaded:
            try:
                pdf.cell(0, 6, "Note: Chinese characters have been converted to pinyin/English", ln=True)
                pdf.cell(0, 6, "For perfect Chinese display, please use text export instead.", ln=True)
                pdf.ln(3)
            except:
                pass

        # 逐行添加内容
        lines = safe_text.split('\n')
        current_y = pdf.get_y()

        for i, line in enumerate(lines):
            # 检查页面空间
            if current_y > 250:
                pdf.add_page()
                current_y = pdf.get_y()

            try:
                if line.strip():
                    # 限制行长度
                    max_length = 85
                    if len(line) > max_length:
                        # 分割长行
                        words = line.split(' ')
                        current_line = ""
                        for word in words:
                            if len(current_line + word + " ") <= max_length:
                                current_line += word + " "
                            else:
                                if current_line.strip():
                                    try:
                                        current_line.encode('latin-1')
                                        pdf.cell(0, 6, current_line.strip(), ln=True)
                                    except UnicodeEncodeError:
                                        safe_line = ''.join(c for c in current_line if ord(c) < 256)
                                        pdf.cell(0, 6, safe_line.strip(), ln=True)
                                    current_y += 6
                                current_line = word + " "

                        if current_line.strip():
                            try:
                                current_line.encode('latin-1')
                                pdf.cell(0, 6, current_line.strip(), ln=True)
                            except UnicodeEncodeError:
                                safe_line = ''.join(c for c in current_line if ord(c) < 256)
                                pdf.cell(0, 6, safe_line.strip(), ln=True)
                            current_y += 6
                    else:
                        try:
                            line.encode('latin-1')
                            pdf.cell(0, 6, line, ln=True)
                        except UnicodeEncodeError:
                            safe_line = ''.join(c for c in line if ord(c) < 256)
                            pdf.cell(0, 6, safe_line, ln=True)
                        current_y += 6
                else:
                    pdf.ln(3)
                    current_y += 3

            except Exception as e:
                print(f"⚠️ 处理第{i + 1}行时出错: {e}")
                try:
                    pdf.cell(0, 6, f"[Line {i + 1}: Processing Error]", ln=True)
                    current_y += 6
                except:
                    pass

        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 保存文件
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf', prefix='script_')
        temp_file.close()

        try:
            pdf.output(temp_file.name)

            # 验证文件
            if os.path.exists(temp_file.name) and os.path.getsize(temp_file.name) > 100:
                file_size = os.path.getsize(temp_file.name)
                print(f"✅ PDF生成成功: {file_size} bytes, 文件路径: {temp_file.name}")

                # 根据字体加载情况提供不同的状态消息
                if font_loaded:
                    success_msg = f"""✅ PDF导出成功！
📁 文件类型: PDF文档
📊 文件大小: {file_size:,} 字节
🕒 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
✨ 中文支持: 完整支持"""
                else:
                    success_msg = f"""⚠️ PDF导出完成(转换模式)
📁 文件类型: PDF文档
📊 文件大小: {file_size:,} 字节
🕒 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔄 字符处理: 中文已转换为拼音/英文
💡 建议: 如需完美中文显示，请使用文本导出"""

                return gr.update(value=temp_file.name, visible=True), gr.update(value=success_msg, visible=True)
            else:
                print("❌ PDF文件无效")
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

                # 使用增强文本导出作为备用
                text_file = create_enhanced_text_export(text)
                if text_file:
                    return gr.update(value=text_file, visible=True), gr.update(value="📝 PDF生成失败，已自动生成文本格式",
                                                                               visible=True)
                else:
                    return None, gr.update(value="❌ PDF和文本导出都失败了", visible=True)

        except Exception as save_error:
            print(f"❌ 保存PDF失败: {save_error}")
            try:
                os.unlink(temp_file.name)
            except:
                pass

            # 使用增强文本导出作为备用
            text_file = create_enhanced_text_export(text)
            if text_file:
                return gr.update(value=text_file, visible=True), gr.update(value="📝 PDF生成失败，已自动生成文本格式",
                                                                           visible=True)
            else:
                return None, gr.update(value=f"❌ 导出失败: {str(save_error)[:100]}...", visible=True)

    except Exception as e:
        print(f"❌ PDF导出完全失败: {e}")

        # 最后的备用方案
        text_file = create_enhanced_text_export(text)
        if text_file:
            return gr.update(value=text_file, visible=True), gr.update(value="📝 PDF功能异常，已自动生成文本格式",
                                                                       visible=True)
        else:
            return None, gr.update(value=f"❌ 完全导出失败: {str(e)[:100]}...", visible=True)


# 创建全局角色管理器实例
character_manager = CharacterManager()


def build_ui():
    """构建用户界面"""
    # 启动时测试PDF功能
    print("🚀 启动时测试导出功能...")
    test_text = "测试文本：这是一个导出测试。\nTest text: This is an export test.\n测试中文字符处理能力。包含各种符号：！@#￥%……&*（）"
    try:
        # 测试文本导出
        text_result = export_with_smart_format(test_text)
        if text_result[0] and text_result[0].value:
            print(f"✅ 文本导出测试成功")
            # 清理测试文件
            try:
                if os.path.exists(text_result[0].value):
                    os.unlink(text_result[0].value)
                    print("🧹 文本测试文件已清理")
            except:
                pass
        else:
            print("❌ 文本导出测试失败")

        # 测试PDF导出
        pdf_result = export_pdf_with_status(test_text)
        if pdf_result[0] and pdf_result[0].value:
            print(f"✅ PDF导出测试成功")
            # 清理测试文件
            try:
                if os.path.exists(pdf_result[0].value):
                    os.unlink(pdf_result[0].value)
                    print("🧹 PDF测试文件已清理")
            except:
                pass
        else:
            print("⚠️ PDF导出测试失败，但有文本备用方案")

    except Exception as e:
        print(f"❌ 导出测试异常: {e}")

    # 获取初始角色列表
    initial_choices = character_manager.get_dropdown_choices()
    print(f"🚀 界面启动：发现 {len(character_manager.characters)} 个角色")
    if initial_choices:
        print(f"🚀 初始角色选项: {initial_choices}")
    else:
        print("📝 当前没有角色，请先添加角色")

    custom_css = """
    .gradio-container {
        max-width: 1400px !important;
        margin: auto;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 15px;
    }
    .gr-box, .gr-form {
        background: rgba(255, 255, 255, 0.95) !important;
        border-radius: 10px !important;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        padding: 15px !important;
        margin: 10px 0 !important;
    }
    .gr-button-primary {
        background: linear-gradient(45deg, #667eea, #764ba2) !important;
        border: none !important;
        border-radius: 8px !important;
        color: white !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
    }
    .gr-button-primary:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 5px 15px rgba(0,0,0,0.2) !important;
    }
    .gr-button-secondary {
        background: linear-gradient(45deg, #f093fb, #f5576c) !important;
        border: none !important;
        border-radius: 8px !important;
        color: white !important;
        font-weight: 600 !important;
    }
    .character-image {
        max-width: 300px;
        max-height: 300px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    .refresh-button {
        font-size: 18px;
    }
    .clear-button {
        background-color: #f0f0f0;
        border: 1px solid #ccc;
    }
    .clear-button:hover {
        background-color: #e0e0e0;
    }
    .simple-divider {
        text-align: center; 
        color: #888; 
        margin: 20px 0;
        background: white;
        border: none;
    }
    .title-text {
        text-align: center;
        color: white;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        margin-bottom: 20px;
    }
    .pdf-status {
        background: #f8f9fa !important;
        border: 1px solid #e9ecef !important;
        border-radius: 6px !important;
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace !important;
        font-size: 13px !important;
    }
    .pdf-output {
        border: 2px dashed #007bff !important;
        border-radius: 8px !important;
        background: #f8f9fa !important;
        padding: 15px !important;
    }
    """

    with gr.Blocks(css=custom_css, title="剧境生成器 Pro") as demo:
        gr.HTML("""
        <div class="title-text">
            <h1 style="font-size: 3em; margin: 0;">🎭 剧境生成器 Pro</h1>
            <p style="font-size: 1.2em; margin: 10px 0;">AI驱动的智能剧本创作平台 - 增强版</p>
            <p>基于 DeepSeek 大模型，支持千帆ERNIE IRAG AI角色头像生成</p>
            <p>📮 联系作者：<a href="mailto:yuntongxu7@gmail.com" style="color: #fff;">yuntongxu7@gmail.com</a></p>
        </div>
        """)

        history_state = gr.State([])

        with gr.Tabs():
            with gr.TabItem("🎬 剧本创作"):
                with gr.Row():
                    with gr.Column():
                        title = gr.Textbox(label="📝 剧本标题", placeholder="例如：《失落之城》")

                        with gr.Row():
                            with gr.Column(scale=4):
                                character_dropdown = gr.Dropdown(
                                    label="从档案中选择角色（可多选）",
                                    choices=initial_choices,
                                    multiselect=True,
                                    interactive=True,
                                    info="从已保存的角色档案中选择"
                                )
                            with gr.Column(scale=1, min_width=100):
                                refresh_char_btn = gr.Button("🔄 刷新", size="sm", elem_classes="refresh-button")

                        gr.HTML("<div class='simple-divider'>或</div>")

                        manual_roles = gr.Textbox(
                            label="手动输入角色设定",
                            placeholder="例如：李雷（探险家）、韩梅梅（考古学家）",
                            lines=2,
                            info="可以直接输入角色信息，格式：角色名（角色类型）"
                        )

                        with gr.Row():
                            style = gr.Dropdown(
                                label="剧本风格",
                                choices=["悬疑", "科幻", "校园", "古风", "现实主义", "喜剧", "动作"],
                                value="悬疑"
                            )
                            temperature = gr.Slider(
                                label="创意程度",
                                minimum=0.2, maximum=1.2, value=0.9, step=0.1
                            )

                        background = gr.Textbox(label="背景设定", placeholder="例如：21世纪的北京地下古墓")
                        prompt = gr.Textbox(label="剧情提示词", lines=4, placeholder="描述一个开场场景或转折设定...")

                        with gr.Row():
                            tone = gr.Textbox(label="语气风格（可选）", placeholder="如：幽默、紧张、感人...")
                            word_limit = gr.Number(label="目标字数（可选）", value=300, precision=0)

                        with gr.Row():
                            submit = gr.Button("🎬 生成剧本", variant="primary", size="lg")
                            continue_button = gr.Button("➕ 续写", variant="secondary")
                            clear = gr.Button("🧹 清空", size="sm")

                    with gr.Column():
                        output = gr.Textbox(label="📖 生成结果", lines=24, interactive=True)

                        with gr.Row():
                            timestamp = gr.Textbox(label="生成时间", interactive=False, scale=2)
                            history_dropdown = gr.Dropdown(label="历史记录", choices=[], interactive=True, scale=3)
                            restore_button = gr.Button("⏪ 恢复", scale=1)

                        gr.Markdown("### 📄 导出功能")
                        gr.Markdown("**多种格式导出，完美支持中文字符**")
                        gr.Markdown("💡 **推荐使用**: 文本格式导出，完美支持中文显示，文件小巧且兼容性好")

                        with gr.Row():
                            text_export_btn = gr.Button("📝 导出文本 (推荐)", variant="primary", size="lg")
                            pdf_export_btn = gr.Button("📄 导出PDF (备用)", variant="secondary", size="lg")

                        with gr.Row():
                            export_output = gr.File(
                                label="📎 下载文件",
                                visible=False,
                                file_count="single",
                                file_types=[".txt", ".pdf"],
                                interactive=False,
                                elem_classes="pdf-output"
                            )

                        export_status = gr.Textbox(
                            label="📋 导出状态",
                            interactive=False,
                            visible=False,
                            lines=4,
                            placeholder="等待导出...",
                            elem_classes="pdf-status"
                        )

            with gr.TabItem("👤 角色档案管理"):
                with gr.Row():
                    with gr.Column(scale=2):
                        gr.Markdown("### ✏️ 角色信息")

                        # 角色信息输入
                        char_inputs = [
                            gr.Textbox(label="角色姓名", placeholder="角色的姓名"),
                            gr.Textbox(label="角色类型", placeholder="如：主角、反派、配角等"),
                            gr.Textbox(label="年龄", placeholder="如：25岁"),
                            gr.Textbox(label="外貌特征", lines=2, placeholder="身高、体型、特征等"),
                            gr.Textbox(label="性格特点", lines=2, placeholder="性格特点描述"),
                            gr.Textbox(label="背景故事", lines=3, placeholder="成长经历、职业等"),
                            gr.Textbox(label="习惯/特点", lines=2, placeholder="如：说话方式、小动作等"),
                            gr.Textbox(label="与其他角色关系", lines=2, placeholder="与主要角色的关系")
                        ]

                        character_name, role_type, age, appearance, personality, background_story, habits, relationships = char_inputs

                        with gr.Row():
                            add_character_btn = gr.Button("➕ 添加角色", variant="primary")
                            update_character_btn = gr.Button("✏️ 更新角色", variant="secondary")
                            delete_character_btn = gr.Button("🗑️ 删除角色", variant="stop")

                        with gr.Row():
                            clear_form_btn = gr.Button("🧹 清空表单", elem_classes="clear-button")

                        # 图片生成区域
                        gr.Markdown("### 🎨 角色头像生成")
                        gr.Markdown("**使用千帆ERNIE IRAG进行AI绘画，支持中文描述**")
                        generate_image_btn = gr.Button("🎨 生成角色头像", variant="secondary", size="lg")

                        character_index = gr.Number(label="编辑角色索引", visible=False, value=-1)
                        message_box = gr.Textbox(label="操作提示", interactive=False, visible=False)

                    with gr.Column(scale=2):
                        gr.Markdown("### 📋 角色列表")

                        character_list = gr.Dropdown(
                            label="选择角色",
                            choices=initial_choices,
                            interactive=True
                        )

                        character_image = gr.Image(
                            label="角色头像",
                            elem_classes="character-image",
                            show_label=True,
                            interactive=False
                        )

                        character_preview = gr.Textbox(
                            label="角色档案预览",
                            lines=10,
                            interactive=False
                        )

                        refresh_btn = gr.Button("🔄 刷新角色列表")

        # === 事件处理函数 ===

        def update_dropdowns():
            """更新角色下拉菜单"""
            choices = character_manager.get_dropdown_choices()
            print(f"🔄 更新下拉菜单，当前选项: {choices}")
            return [gr.update(choices=choices, value=None), gr.update(choices=choices, value=None)]

        def clear_form():
            """清空表单"""
            return [""] * 8 + [-1, "", gr.update(visible=False)]

        def show_message(msg, is_error=False):
            """显示操作消息"""
            return gr.update(value=f"{'❌' if is_error else '✅'} {msg}", visible=True)

        # 角色管理事件处理
        def add_character_handler(*inputs):
            """添加角色处理函数"""
            name, role_type = inputs[0].strip(), inputs[1].strip()

            if not name:
                return update_dropdowns() + list(inputs) + [-1, "", show_message("角色姓名不能为空", True)]

            if character_manager.character_exists(name, role_type):
                return update_dropdowns() + list(inputs) + [-1, "",
                                                            show_message(f"角色 '{name} ({role_type})' 已存在", True)]

            char_data = {key: val.strip() for key, val in zip(
                ['name', 'role_type', 'age', 'appearance', 'personality', 'background_story', 'habits',
                 'relationships'],
                inputs
            )}

            character_manager.add_character(char_data)
            return update_dropdowns() + [""] * 8 + [-1, "", show_message(f"角色 '{name}' 添加成功！")]

        def update_character_handler(index, *inputs):
            """更新角色处理函数"""
            if index == -1:
                return update_dropdowns() + list(inputs) + [index, "", show_message("请先选择要更新的角色", True)]

            name = inputs[0].strip()
            if not name:
                return update_dropdowns() + list(inputs) + [index, "", show_message("角色姓名不能为空", True)]

            char_data = {key: val.strip() for key, val in zip(
                ['name', 'role_type', 'age', 'appearance', 'personality', 'background_story', 'habits',
                 'relationships'],
                inputs
            )}

            character_manager.update_character(index, char_data)
            return update_dropdowns() + [""] * 8 + [-1, "", show_message(f"角色 '{name}' 更新成功！")]

        def delete_character_handler(index):
            """删除角色处理函数"""
            if index == -1:
                return update_dropdowns() + [""] * 8 + [-1, "", show_message("请先选择要删除的角色", True)]

            char_name = character_manager.characters[index]['name']
            character_manager.delete_character(index)
            return update_dropdowns() + [""] * 8 + [-1, "", show_message(f"角色 '{char_name}' 删除成功！")]

        def load_character_with_image(character_name):
            """加载角色信息并显示图片"""
            print(f"🔍 尝试加载角色: {character_name}")

            if not character_name:
                return [""] * 8 + [-1, "请选择角色", gr.update(visible=False), None]

            try:
                char_index = int(character_name.split(":")[0])
                print(f"🔍 解析角色索引: {char_index}")

                if 0 <= char_index < len(character_manager.characters):
                    char = character_manager.characters[char_index]
                    print(f"✅ 成功加载角色: {char['name']}")

                    formatted = ROLE_TEMPLATE.format(**char)
                    image = get_character_image(char_index)
                    return list(char.values())[:-1] + [char_index, formatted, gr.update(visible=False), image]
                else:
                    print(f"❌ 角色索引超出范围: {char_index} >= {len(character_manager.characters)}")
            except (ValueError, IndexError) as e:
                print(f"❌ 解析角色失败: {e}")

            return [""] * 8 + [-1, "未找到角色", gr.update(visible=False), None]

        # 图片生成事件
        def generate_image_handler(character_index):
            """生成头像处理函数"""
            image, message = generate_character_image(character_index)
            is_error = "失败" in message or "出错" in message
            return (
                image,
                show_message(message, is_error),
                *update_dropdowns()
            )

        # 剧本生成事件
        def generate_with_history(*args):
            """生成剧本并保存历史"""
            script = generate_script(*args[:-1])
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            word_count = count_words(script)

            history = args[-1] if isinstance(args[-1], list) else []
            label = f"{timestamp_str}（{word_count}字中文）"
            history.append({"label": label, "text": script, "word_count": word_count})

            output_label = f"📖 生成结果 ({word_count} 字中文)"

            return (
                gr.update(value=script, label=output_label),
                timestamp_str,
                history,
                gr.update(choices=[item["label"] for item in history])
            )

        def continue_script(text, temperature, word_limit):
            """续写剧本"""
            continuation = generate_script("", [], "", "", "", text, "", temperature, word_limit, append=True)
            full_text = text + "\n\n" + continuation
            word_count = count_words(full_text)
            output_label = f"📖 生成结果 ({word_count} 字中文)"
            return gr.update(value=full_text, label=output_label), datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def restore_history(choice_label, history, current_text):
            """从历史记录恢复"""
            for item in history:
                if item["label"] == choice_label:
                    word_count = count_words(item["text"])
                    output_label = f"📖 生成结果 ({word_count} 字中文)"
                    return gr.update(value=item["text"], label=output_label)
            return gr.update(value=current_text)

        # === 事件绑定 ===

        # 定义输出组件顺序
        char_outputs = [character_dropdown, character_list] + char_inputs + [character_index, character_preview,
                                                                             message_box]

        # 角色管理事件
        add_character_btn.click(add_character_handler, char_inputs, char_outputs)
        update_character_btn.click(update_character_handler, [character_index] + char_inputs, char_outputs)
        delete_character_btn.click(delete_character_handler, [character_index], char_outputs)
        clear_form_btn.click(clear_form, [], char_inputs + [character_index, character_preview, message_box])

        # 刷新事件
        for btn in [refresh_char_btn, refresh_btn]:
            btn.click(update_dropdowns, [], [character_dropdown, character_list])

        # 角色选择事件
        character_list.change(
            load_character_with_image,
            [character_list],
            char_inputs + [character_index, character_preview, message_box, character_image]
        )

        # 图片生成事件
        generate_image_btn.click(
            generate_image_handler,
            [character_index],
            [character_image, message_box, character_dropdown, character_list]
        )

        # 剧本生成事件
        submit.click(
            generate_with_history,
            [title, character_dropdown, manual_roles, style, background, prompt, tone, temperature, word_limit,
             history_state],
            [output, timestamp, history_state, history_dropdown]
        )

        continue_button.click(continue_script, [output, temperature, word_limit], [output, timestamp])
        restore_button.click(restore_history, [history_dropdown, history_state, output], [output])

        clear.click(
            lambda: ["", [], "", "", "", "", "", 0.9, 300],
            [], [title, character_dropdown, style, background, prompt, tone, manual_roles, temperature, word_limit]
        )

        def safe_export_handler(text, export_type="text"):
            """安全的导出处理函数"""
            if not text or not text.strip():
                return None, gr.update(value="❌ 没有内容可导出，请先生成剧本内容", visible=True)

            print(f"📄 开始处理{export_type}导出，内容长度: {len(text)} 字符")

            try:
                if export_type == "text":
                    return export_with_smart_format(text)
                elif export_type == "pdf":
                    return export_pdf_with_status(text)
                else:
                    return None, gr.update(value="❌ 未知的导出类型", visible=True)
            except Exception as e:
                error_msg = f"❌ 导出过程中发生错误: {str(e)[:150]}..."
                print(f"❌ {export_type}导出异常: {e}")
                return None, gr.update(value=error_msg, visible=True)

        # 导出事件绑定
        text_export_btn.click(
            lambda text: safe_export_handler(text, "text"),
            [output],
            [export_output, export_status]
        )

        pdf_export_btn.click(
            lambda text: safe_export_handler(text, "pdf"),
            [output],
            [export_output, export_status]
        )

        # 示例数据
        gr.Examples(
            label="💡 创作示例（点击可一键填入）",
            examples=[
                ["《未来迷城》", [], "艾拉（黑客）、机器人守卫（AI）", "科幻", "2050年赛博朋克城市",
                 "一场黑客入侵引发的连锁反应...", "冷峻科幻", 0.8, 300],
                ["《校园奇遇》", [], "小明（学生）、神秘转校生（??）", "校园", "春天的樱花高中",
                 "转校生的真实身份让所有人震惊...", "青春活泼", 1.0, 250],
                ["《古宅密码》", [], "探险家张博士（考古学家）、村民老王（向导）", "悬疑", "深山古宅，雷雨夜",
                 "一张神秘地图指向了埋藏百年的秘密...", "紧张悬疑", 0.9, 350]
            ],
            inputs=[title, character_dropdown, manual_roles, style, background, prompt, tone, temperature, word_limit]
        )

    return demo


if __name__ == '__main__':
    demo = build_ui()
    demo.launch()