# from minio import Minio
# from minio.error import S3Error
import os
from typing import Optional, Union
from datetime import timedelta, datetime
import requests

def get_filename_from_url_simple(url):
    # 按 ? 分割，取前面的路径部分
    path_part = url.split('?')[0]
    # 按 / 分割，取最后一段
    filename = path_part.split('/')[-1]
    return filename

def download_minio_file(minio_url, save_path):
    try:
        # 发送 GET 请求，流式下载（适合大文件）
        with requests.get(minio_url, stream=True) as response:
            # 检查请求是否成功
            response.raise_for_status()
            # 写入本地文件
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        print(f"文件已成功保存到: {save_path}")
    except requests.exceptions.RequestException as e:
        print(f"下载失败: {e}")
        return False
    return True

# 调用函数下载
# download_minio_file(minio_url, local_path)
# --------------------------
# 2. 使用预上传URL上传文件
# --------------------------
def upload_file_with_presigned_url(presigned_url, file_path):
    """
    使用预签名URL上传文件
    
    参数:
        presigned_url: 预生成的上传URL
        file_path: 本地文件路径
    """
    if not presigned_url:
        print("预上传URL无效")
        return False
    
    try:
        # 以二进制模式打开文件
        with open(file_path, 'rb') as file_data:
            # 发送PUT请求上传文件
            response = requests.put(
                presigned_url,
                data=file_data,
                headers={'Content-Type': 'application/octet-stream'}
            )
        
        # 检查响应状态
        if response.status_code == 200:
            print("文件上传成功")
            return True
        else:
            print(f"文件上传失败，状态码: {response.status_code}, 响应: {response.text}")
            return False
            
    except Exception as e:
        print(f"上传文件时发生错误: {e}")
        return False

# ------------------- 示例使用 -------------------
if __name__ == "__main__":
    # url = "http://10.1.0.89:9000/fileupload/0/3f2aea75f7cd41dfb5f9e7d6fd9c85e3.txt?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20260106%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260106T021925Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=b68b5d5662f2b5390ce8c0dd652be3e2640072eef5a22fc490031b07b5a08e83"
    url = "http://10.1.0.87:9000/documenttranslate/2205.05832v3-mono.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20260106%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260106T082740Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=d939b1820ac79831425f6bc1d481933a13be70f398574016f819d39c8538af0d"
    print(get_filename_from_url_simple(url))
    print(download_minio_file(url, "/home/ubuntu/jiangyongyu/project/document_translation/pdftranslate_src/app/uploads/2205.05832v31-mono.pdf"))
    exit()
    # 1. 配置 MinIO 连接信息
    MINIO_CONFIG = {
        "endpoint": minio_address,
        "access_key": minio_user,  # 替换为实际值
        "secret_key": minio_password,  # 替换为实际值
        "default_bucket": config_default_bucket  # 可选默认存储桶
    }
    
    # 2. 创建上传器实例
    uploader = MinioFileUploader(**MINIO_CONFIG)
    
    # 3. 上传文件（核心调用）
    # 方式1：使用默认存储桶，对象名=本地文件名
    local_file_path1 = "/home/ubuntu/jiangyongyu/project/document_translation/pdftranslate_src/app/upload/Scaling-dual.pdf"  # 替换为实际文件路径
    result1 = uploader.upload_file(local_file_path1)
    if result1:
        print(f"\n上传结果1: {result1}")
    uploader.close()
    exit()
    # 方式2：指定存储桶和自定义对象名
    local_file_path2 = "/path/to/your/file2.jpg"
    result2 = uploader.upload_file(
        local_file_path=local_file_path2,
        bucket_name="my-image-bucket",
        object_name="custom-image-name.jpg"
    )
    
    # 4. 检查上传结果
    if result1:
        print(f"\n上传结果1: {result1}")
    # if result2:
    #     print(f"\n上传结果2: {result2}")
    
    # 5. 关闭连接（预留接口）
    uploader.close()