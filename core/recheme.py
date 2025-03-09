import requests, base64
from typing import Dict, List, Optional, Union
from core.logs import log, log_print

logger = log()

class RechemeAPI:
    """录播姬 API"""
    
    def __init__(self, host: str, name: str, basic_auth: bool = False, username: str = "", password: str = "", manage: bool = True):
        """
        初始化录播姬 API
        :param host: 录播姬服务器地址
        :param name: 录播姬实例名称
        :param basic_auth: 是否启用 Basic 认证
        :param username: Basic 认证用户名
        :param password: Basic 认证密码
        :param manage: 是否允许管理操作
        """
        self.host = host.rstrip('/')
        self.name = name
        self.manage = manage
        self.session = requests.Session()
        self.session.trust_env = False
        self.headers = {}
        
        if basic_auth and username and password:
            auth_str = f"{username}:{password}"
            encoded_credentials = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
            self.headers["Authorization"] = f"Basic {encoded_credentials}"
            logger.debug(f"[录播姬] {self.name} Basic认证已配置")

    def _make_request(self, endpoint: str, method: str = "GET", json: Dict = None) -> Optional[Union[Dict, List]]:
        """
        发送 HTTP 请求到录播姬 API
        :param endpoint: API 端点
        :param method: HTTP 方法
        :param json: POST 请求的 JSON 数据
        :return: API 响应数据
        """
        url = f"{self.host}/api/{endpoint}"
        try:
            response = self.session.request(method, url, headers=self.headers, json=json, timeout=3)
            if response.status_code in [200, 201]:
                data = response.json()
                return data
            else:
                log_print(f"[录播姬] {self.name} 请求失败，状态码: {response.status_code}, URL: {url}", "ERROR")
                return None
        except requests.exceptions.Timeout:
            log_print(f"[录播姬] {self.name} 请求超时, URL: {url}", "ERROR")
            return None
        except Exception as e:
            log_print(f"[录播姬] {self.name} 请求异常: {e}, URL: {url}", "ERROR")
            return None

    def get_rooms(self) -> List[Dict]:
        """获取所有直播间信息"""
        data = self._make_request("room")
        if not data:
            return []
            
        for item in data:
            item["recServer"] = {
                "recName": self.name,
                "recType": "recheme",
                "recHost": self.host,
                "recManage": self.manage
            }
        return data

    def get_room(self, room_id: str) -> Optional[Dict]:
        """
        获取指定直播间信息
        :param room_id: 房间号
        """
        data = self._make_request(f"room/{room_id}")
        if not data:
            return None
            
        data["recServer"] = {
            "recName": self.name,
            "recType": "recheme",
            "recHost": self.host,
            "recManage": self.manage
        }
        return data

    def get_room_stats(self, room_id: str) -> Optional[Dict]:
        """
        获取直播间录制统计信息
        :param room_id: 房间号
        """
        return self._make_request(f"room/{room_id}/stats")

    def get_room_iostats(self, room_id: str) -> Optional[Dict]:
        """
        获取直播间 IO 统计信息
        :param room_id: 房间号
        """
        return self._make_request(f"room/{room_id}/iostats")

    def get_room_config(self, room_id: str) -> Optional[Dict]:
        """
        获取直播间设置
        :param room_id: 房间号
        """
        return self._make_request(f"room/{room_id}/config")

    def _check_manage_permission(self, operation: str) -> bool:
        """检查是否有管理权限"""
        if not self.manage:
            log_print(f"[录播姬] {self.name} 未启用管理功能，禁止{operation}操作", "ERROR")
            return False
        return True

    def create_room(self, room_id: int, auto_record: bool = True) -> Optional[Dict]:
        """
        创建新的直播间
        :param room_id: 房间号
        :param auto_record: 是否启用自动录制
        :return: 创建结果
        """
        if not self._check_manage_permission("创建房间"):
            return None
        data = {
            "roomId": room_id,
            "autoRecord": auto_record
        }
        response = self._make_request("room", method="POST", json=data)
        if response:
            response["recServer"] = {
                "recName": self.name,
                "recType": "recheme",
                "recHost": self.host,
                "recManage": self.manage
            }
        return response 

    def update_room_config(self, room_id: int, config: Dict) -> Optional[Dict]:
        """
        修改直播间设置
        :param room_id: 房间号
        :param config: 配置信息
        :return: 更新结果
        """
        if not self._check_manage_permission("修改设置"):
            return None
        return self._make_request(f"room/{room_id}/config", method="POST", json=config)

    def start_recording(self, room_id: int) -> Optional[Dict]:
        """
        开始录制
        :param room_id: 房间号
        :return: 操作结果
        """
        if not self._check_manage_permission("开始录制"):
            return None
        return self._make_request(f"room/{room_id}/start", method="POST")

    def stop_recording(self, room_id: int) -> Optional[Dict]:
        """
        停止录制
        :param room_id: 房间号
        :return: 操作结果
        """
        if not self._check_manage_permission("停止录制"):
            return None
        return self._make_request(f"room/{room_id}/stop", method="POST")

    def split_recording(self, room_id: int) -> Optional[Dict]:
        """
        手动分段
        :param room_id: 房间号
        :return: 操作结果
        """
        if not self._check_manage_permission("手动分段"):
            return None
        return self._make_request(f"room/{room_id}/split", method="POST")

    def refresh_room(self, room_id: int) -> Optional[Dict]:
        """
        刷新直播间信息
        :param room_id: 房间号
        :return: 刷新结果
        """
        if not self._check_manage_permission("刷新房间"):
            return None
        return self._make_request(f"room/{room_id}/refresh", method="POST")

    def delete_room(self, room_id: int) -> Optional[Dict]:
        """
        删除直播间
        :param room_id: 房间号
        :return: 删除结果
        """
        if not self._check_manage_permission("删除房间"):
            return None
        return self._make_request(f"room/{room_id}", method="DELETE") 