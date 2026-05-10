from minio import Minio
from minio.error import S3Error
import os
from typing import Optional, Union
from datetime import timedelta, datetime

import yaml
with open('./config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.load(f.read(), Loader=yaml.FullLoader)

minio_address = config['minio_address']
minio_user = config['minio_user']
minio_password = config['minio_password']
config_default_bucket = config['default_bucket']

class MinioFileUploader:
    """MinIO 文件上传工具类"""
    
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
        default_bucket: Optional[str] = None
    ):
        """
        初始化 MinIO 上传客户端
        
        Args:
            endpoint: MinIO 服务地址 (例如: "127.0.0.1:9000")
            access_key: MinIO 访问密钥
            secret_key: MinIO 密钥
            secure: 是否使用 HTTPS，默认 False
            default_bucket: 默认存储桶名称，可选
        """
        # 初始化客户端
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )
        self.default_bucket = default_bucket
        self.endpoint = endpoint
    
    def _ensure_bucket_exists(self, bucket_name: str) -> bool:
        """
        确保存储桶存在，不存在则创建
        内部辅助方法，不对外暴露
        
        Args:
            bucket_name: 存储桶名称
        
        Returns:
            bool: 创建/存在成功返回 True，失败返回 False
        """
        try:
            if not self.client.bucket_exists(bucket_name):
                self.client.make_bucket(bucket_name)
                print(f"存储桶 '{bucket_name}' 已创建")
            return True
        except S3Error as e:
            print(f"创建/检查存储桶失败: {e}")
            return False
    
    def upload_file(
        self,
        local_file_path: str,
        bucket_name: Optional[str] = None,
        object_name: Optional[str] = None,
        overwrite: bool = True
    ) -> Union[bool, dict]:
        """
        上传本地文件到 MinIO
        
        Args:
            local_file_path: 本地文件路径
            bucket_name: 存储桶名称，若未指定则使用默认存储桶
            object_name: 上传后的对象名称，默认使用本地文件名
            overwrite: 是否覆盖已存在的对象，默认 True
        
        Returns:
            Union[bool, dict]: 成功返回包含上传信息的字典，失败返回 False
        """
        # 检查默认存储桶和传入存储桶
        target_bucket = bucket_name or self.default_bucket
        if not target_bucket:
            print("错误：未指定存储桶名称，且未设置默认存储桶")
            return False
        
        # 检查本地文件是否存在
        if not os.path.exists(local_file_path):
            print(f"错误：本地文件 '{local_file_path}' 不存在")
            return False
        
        # 确保文件是文件而不是目录
        if not os.path.isfile(local_file_path):
            print(f"错误：'{local_file_path}' 不是一个有效的文件")
            return False
        
        # 确保存储桶存在
        if not self._ensure_bucket_exists(target_bucket):
            return False
        
        # 确定对象名称
        target_object_name = object_name or os.path.basename(local_file_path)
        
        try:
            # 获取文件大小
            file_size = os.stat(local_file_path).st_size
            
            # 上传文件
            result = self.client.fput_object(
                bucket_name=target_bucket,
                object_name=target_object_name,
                file_path=local_file_path
            )
            res = self.client.get_presigned_url("GET", target_bucket, target_object_name, expires=timedelta(days=7))
            # res就是获取文件的url
            print(res)
            print(result)
            # 构造返回信息
            upload_info = {
                "status": "success",
                "local_file": local_file_path,
                "bucket": target_bucket,
                "object_name": target_object_name,
                "file_size": file_size,
                "etag": result.etag,  # MinIO 返回的文件唯一标识
                "version_id": result.version_id,
                "url": res
            }
            
            print(f"\n文件上传成功！")
            print(f"本地文件: {local_file_path}")
            print(f"MinIO 存储桶: {target_bucket}")
            print(f"MinIO 对象名: {target_object_name}")
            print(f"文件大小: {file_size} 字节")
            print(f"ETag: {result.etag}")
            
            return upload_info
        
        except S3Error as e:
            print(f"MinIO 上传错误: {e}")
            return False
        except Exception as e:
            print(f"上传失败: {e}")
            return False
    
    def close(self):
        """关闭客户端连接（MinIO Python 客户端无显式关闭方法，此处为预留接口）"""
        print(f"已断开与 {self.endpoint} 的 MinIO 连接")

# ------------------- 示例使用 -------------------
if __name__ == "__main__":
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
    local_file_path1 = "/home/ubuntu/jiangyongyu/project/document_translation/pdftranslate_src/app/uploads/2205.05832v3-mono.pdf"  # 替换为实际文件路径
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