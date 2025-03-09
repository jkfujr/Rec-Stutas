import requests
from typing import Dict, List, Optional, Union
from core.logs import log, log_print

logger = log()

class BLRECAPI:
    """BLREC API"""
    
    def __init__(self, host: str, name: str, api_key: str = "", manage: bool = True):
        """
        初始化 BLREC API
        :param host: BLREC 服务器地址
        :param name: BLREC 实例名称
        :param api_key: API 密钥
        :param manage: 是否启用管理功能
        """
        self.host = host.rstrip('/')
        self.name = name
        self.manage = manage
        self.session = requests.Session()
        self.session.trust_env = False
        self.headers = {}
        
        if api_key:
            self.headers["x-api-key"] = api_key
            logger.debug(f"[BLREC] {self.name} API密钥已配置")
        
        manage_status = "启用" if self.manage else "禁用"
        logger.debug(f"[BLREC] {self.name} 管理功能{manage_status}")

    def _make_request(self, endpoint: str, method: str = "GET", params: Dict = None, json: Dict = None) -> Optional[Union[Dict, List]]:
        """
        发送 HTTP 请求到 BLREC API
        :param endpoint: API 端点
        :param method: HTTP 方法
        :param params: 查询参数
        :param json: POST 请求的 JSON 数据
        :return: API 响应数据
        """
        if not self.manage and method != "GET":
            log_print(f"[BLREC] {self.name} 管理功能已禁用，拒绝 {method} 请求: {endpoint}", "WARNING")
            return None
            
        url = f"{self.host}/api/v1/{endpoint}"
        try:
            response = self.session.request(
                method, 
                url, 
                headers=self.headers, 
                params=params,
                json=json,
                timeout=3
            )
            if response.status_code in [200, 201]:
                data = response.json()
                return data
            else:
                log_print(f"[BLREC] {self.name} 请求失败，状态码: {response.status_code}, URL: {url}", "ERROR")
                return None
        except requests.exceptions.Timeout:
            log_print(f"[BLREC] {self.name} 请求超时, URL: {url}", "ERROR")
            return None
        except Exception as e:
            log_print(f"[BLREC] {self.name} 请求异常: {e}, URL: {url}", "ERROR")
            return None

    def get_rooms(self, page: int = 1, size: int = 100, select: str = "all") -> List[Dict]:
        """获取所有直播间信息"""
        params = {
            "page": page,
            "size": min(max(size, 10), 100),
            "select": select
        }
        
        data = self._make_request("tasks/data", params=params)
        if not data or not isinstance(data, list):
            return []
            
        for item in data:
            item["recServer"] = {
                "recName": self.name,
                "recType": "blrec",
                "recHost": self.host,
                "recManage": self.manage
            }
        return data

    def get_room(self, room_id: str) -> Optional[Dict]:
        """
        获取指定直播间信息
        :param room_id: 房间号
        :return: 直播间信息
        """
        data = self._make_request(f"tasks/{room_id}/data")
        if not data:
            return None
        
        data["recServer"] = {
            "recName": self.name,
            "recType": "blrec", 
            "recHost": self.host,
            "recManage": self.manage
        }
        return data

    def get_room_stats(self, room_id: str) -> Optional[Dict]:
        """
        获取直播间状态信息
        :param room_id: 房间号
        :return: 状态信息
        """
        return self._make_request(f"tasks/{room_id}/stats")

    def get_room_status(self, room_id: str) -> Optional[Dict]:
        """
        获取直播间运行状态
        :param room_id: 房间号
        :return: 运行状态
        """
        return self._make_request(f"tasks/{room_id}/status")

    def get_room_config(self, room_id: str) -> Optional[Dict]:
        """
        获取直播间配置
        :param room_id: 房间号
        :return: 配置信息
        """
        return self._make_request(f"tasks/{room_id}/config")

    def update_room_config(self, room_id: str, config: Dict) -> Optional[Dict]:
        """
        更新直播间配置
        :param room_id: 房间号
        :param config: 配置信息
        :return: 更新结果
        """
        return self._make_request(f"tasks/{room_id}/config", method="PUT", json=config)

    def start_recording(self, room_id: str) -> Optional[Dict]:
        """
        开始录制
        :param room_id: 房间号
        :return: 操作结果
        """
        return self._make_request(f"tasks/{room_id}/start", method="POST")

    def stop_recording(self, room_id: str) -> Optional[Dict]:
        """
        停止录制
        :param room_id: 房间号
        :return: 操作结果
        """
        return self._make_request(f"tasks/{room_id}/stop", method="POST")

    def delete_room(self, room_id: str) -> Optional[Dict]:
        """
        删除直播间
        :param room_id: 房间号
        :return: 删除结果
        """
        return self._make_request(f"tasks/{room_id}", method="DELETE")

    def create_room(self, room_id: int, auto_record: bool = True) -> Optional[Dict]:
        """创建新的直播间"""
        data = self._make_request(f"tasks/{room_id}", method="POST")
        if not data:
            return None
        
        data["recServer"] = {
            "recName": self.name,
            "recType": "blrec",
            "recHost": self.host,
            "recManage": self.manage
        }
        return data 