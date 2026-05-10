import datetime
import urllib.request
import os
import time
import requests
import json
# import fitz  # pip install pymupdf

def save_file(file_url, upload_folder, file_type="pdf", file_ext=".pdf"):
    # timeee = datetime.datetime.now().strftime('%Y%m%d')
    # root_path = os.path.join(upload_folder, file_type)
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    name_str = "".join(str(time.time()).split("."))
    file_save_path = os.path.join(upload_folder, "{}{}".format(name_str, file_ext))
    try:
        opener = urllib.request.build_opener()
        opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.75 Safari/537.36')]
        urllib.request.install_opener(opener)
        urllib.request.urlretrieve(file_url, file_save_path)
    except Exception as e:
        print("Error occurred when downloading file, error message:")
        print(e)
        file_save_path = None
    return file_save_path

def delete_file_by_path(file_path):
    """
    根据文件路径删除文件
    :param file_path: 要删除的文件路径（字符串）
    :return: 布尔值，删除成功返回 True，失败返回 False
    """
    try:
        # 先检查文件是否存在，避免 FileNotFoundError
        if os.path.isfile(file_path):
            os.remove(file_path)  # 删除文件
            print(f"文件 {file_path} 删除成功")
            return True
        else:
            print(f"文件 {file_path} 不存在，无需删除")
            return False
    except PermissionError:
        print(f"权限不足，无法删除文件 {file_path}")
        return False
    except Exception as e:
        print(f"删除文件 {file_path} 时出错：{e}")
        return False

def request_api(url, request_body):
    

    # 接口URL
    # url = "/document/internal/getPresignedUploadUrl"  # 注意：实际需补充完整域名（如https://your-domain.com）

    # # 请求体（需替换为实际业务参数）
    # request_body = {
    #     "businessType": "translate-result",  # 业务类型：fileupload/translate-result
    #     "uuid": "your-task-uuid-123",       # 业务UUID（如任务ID）
    #     "fileName": "translated_doc.pdf"    # 文件名
    # }

    # 请求头
    headers = {
        "Content-Type": "application/json"
    }

    try:
        # 发送POST请求
        response = requests.post(
            url=url,
            data=json.dumps(request_body),
            headers=headers,
            timeout=30  # 设置30秒超时
        )
        # response.raise_for_status()  # 若响应状态码非200，抛异常

        # 打印响应结果
        # print("请求成功，响应：")
        # return json.dumps(response.json(), indent=2, ensure_ascii=False)
        return response.json()

    except Exception as e:
        print(f"请求失败：{str(e)}")
    return None

def is_scanned_pdf(file_path, text_threshold=10):
    """
    判断PDF文件是扫描版(图片型)还是文字版
    
    Args:
        file_path: PDF文件路径
        text_threshold: 文本长度阈值，小于该值判定为扫描版
        
    Returns:
        bool: True表示是扫描版，False表示是文字版
    """
    # 检查文件是否存在
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    # 检查是否是PDF文件
    if not file_path.lower().endswith('.pdf'):
        raise ValueError("输入文件不是PDF格式")
    
    try:
        # 打开PDF文件
        doc = fitz.open(file_path)
        total_text = ""
        
        # 遍历所有页面提取文本
        for page_num in range(len(doc)):
            page = doc[page_num]
            # 提取页面文本
            page_text = page.get_text().strip()
            total_text += page_text
        
        # 关闭文档
        doc.close()
        
        # 计算有效文本长度（去除空白字符）
        clean_text = ''.join(total_text.split())
        text_length = len(clean_text)
        
        # 判断是否为扫描版
        is_scanned = text_length < text_threshold
        
        # 返回结果和文本长度，方便调试
        return {
            "is_scanned": is_scanned,
            "text_length": text_length,
            "file_type": "扫描版PDF" if is_scanned else "文字版PDF"
        }
        
    except Exception as e:
        raise Exception(f"处理PDF时出错: {str(e)}")

if __name__ == "__main__":
    UPLOAD_FOLDER = 'uploads'
    print(save_file("http://10.1.0.87:9000/documenttranslate/Scaling-dual.pdf", UPLOAD_FOLDER))
    exit()
    delete_file_by_path("uploads/1767606007440908.pdf")

    # 替换为你的PDF文件路径
    pdf_path = "test.pdf"
    
    try:
        result = is_scanned_pdf(pdf_path)
        print(f"文件: {pdf_path}")
        print(f"判定结果: {result['file_type']}")
        print(f"提取的有效文本长度: {result['text_length']}")
    except Exception as e:
        print(f"错误: {e}")