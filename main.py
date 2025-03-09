import sys, requests, uvicorn, asyncio
from ruamel.yaml import YAML
from typing import List, Dict, Union
from fastapi import FastAPI, HTTPException, Depends, Form, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from pydantic import BaseModel
from datetime import datetime
from contextlib import asynccontextmanager

from core.logs import log, log_print
from core.recheme import RechemeAPI
from core.blrec import BLRECAPI
from core.auth import Auth, get_current_user, requires_auth

# 变量
## 数据缓存
cached_data = None
## 配置
config = None
## Session
session = requests.Session()
## 禁用环境变量代理
session.trust_env = False

# 全局认证对象
auth = None

# run
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        global config, auth
        config = load_config()
        auth = Auth(config)
        logger.debug("[启动] 配置加载成功")
    except Exception as e:
        logger.error(f"[启动] 配置加载失败: {e}")
        raise e
    
    yield
    
    logger.debug("[关闭] 应用正在关闭")

app = FastAPI(lifespan=lifespan)

logger = log()

# 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 恢复正确的静态文件挂载
app.mount("/assets", StaticFiles(directory="web/assets"), name="assets")

@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        with open("web/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"[前端] 加载前端页面失败: {e}")
        return f"<html><body><h1>前端加载失败</h1><p>{str(e)}</p></body></html>"

# 数据模型
class CreateRoomRequest(BaseModel):
    roomId: int
    autoRecord: bool = True
    recType: str = None
    recName: str = None

    class Config:
        populate_by_name = True

class RecServerInfo(BaseModel):
    recName: str
    recType: str
    recHost: str
    recStatus: str
    recManage: bool

class RoomConfigRequest(BaseModel):
    danmaku: bool = True
    gift: bool = True
    guard: bool = True
    sc: bool = True

    class Config:
        populate_by_name = True

class BatchCreateRoomRequest(BaseModel):
    rooms: List[CreateRoomRequest]
    recType: str = None
    recName: str = None

    class Config:
        populate_by_name = True

class AddServerRequest(BaseModel):
    recType: str
    recName: str
    url: str
    manage: bool = True
    basic: bool = None
    basicUser: str = None
    basicPass: str = None
    basicKey: str = None

    class Config:
        populate_by_name = True

class BatchAddServerRequest(BaseModel):
    servers: List[AddServerRequest]

    class Config:
        populate_by_name = True

class DeleteRoomRequest(BaseModel):
    roomId: int
    recType: str = None
    recName: str = None

class BatchDeleteRoomRequest(BaseModel):
    rooms: List[DeleteRoomRequest]

class LoginRequest(BaseModel):
    username: str
    password: str

class DeleteServerRequest(BaseModel):
    recName: str
    recType: str

class BatchDeleteServerRequest(BaseModel):
    servers: List[DeleteServerRequest]

# 配置
def load_config() -> Dict:
    try:
        yaml = YAML()
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.load(f)
        if "AUTH" not in config:
            config["AUTH"] = {}
            
        if not isinstance(config["AUTH"], dict):
            raise ValueError("AUTH 配置必须是一个字典")
            
        # 默认值
        auth_defaults = {
            "ENABLE": False,
            "AUTH_KEY": "114514",
            "AUTH_KEY_EXPIRE": 60 * 24,
            "AUTH_USER": {}
        }  
        for key, default_value in auth_defaults.items():
            if key not in config["AUTH"]:
                config["AUTH"][key] = default_value
                
        return config
    except Exception as e:
        log_print(f"加载配置文件失败: {e}", "ERROR")
        raise

def save_config(config):
    try:
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        
        with open("config.yaml", "w", encoding="utf-8") as file:
            yaml.dump(config, file)
            log_print("[配置] 配置文件保存成功")
        return True
    except Exception as e:
        log_print(f"[配置] 保存配置文件失败: {e}", "ERROR")
        return False

# 工具函数
async def check_server_status(url: str) -> bool:
    """检查服务器状态"""
    try:
        async with asyncio.timeout(2):
            response = await asyncio.to_thread(
                requests.get, 
                url,
                timeout=2
            )
        return response.status_code == 200
    except:
        return False

async def get_all_recservers() -> List[RecServerInfo]:
    servers = []
    """获取所有录播机信息"""
    if "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    host = api_info.get("URL", "").rstrip('/')
                    manage = api_info.get("MANAGE", True)
                    try:
                        recheme = create_recheme_instance(api_info, rec_name)
                        response = recheme._make_request("room")
                        if response is not None:
                            servers.append(RecServerInfo(
                                recName=rec_name,
                                recType="recheme",
                                recHost=host,
                                recStatus="online",
                                recManage=manage
                            ))
                        else:
                            servers.append(RecServerInfo(
                                recName=rec_name,
                                recType="recheme",
                                recHost=host,
                                recStatus="offline",
                                recManage=manage
                            ))
                    except Exception as e:
                        logger.error(f"[录播姬] {rec_name} 状态检查失败: {e}")
                        servers.append(RecServerInfo(
                            recName=rec_name,
                            recType="recheme",
                            recHost=host,
                            recStatus="error",
                            recManage=manage
                        ))

    if "BLREC" in config:
        for rec_name, api_info_list in config["BLREC"].items():
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    host = api_info.get("URL", "").rstrip('/')
                    manage = api_info.get("MANAGE", True)
                    try:
                        blrec = create_blrec_instance(api_info, rec_name)
                        response = blrec._make_request("tasks/data")
                        if response is not None:
                            servers.append(RecServerInfo(
                                recName=rec_name,
                                recType="blrec",
                                recHost=host,
                                recStatus="online",
                                recManage=manage
                            ))
                        else:
                            servers.append(RecServerInfo(
                                recName=rec_name,
                                recType="blrec",
                                recHost=host,
                                recStatus="offline",
                                recManage=manage
                            ))
                    except Exception as e:
                        logger.error(f"[BLREC] {rec_name} 状态检查失败: {e}")
                        servers.append(RecServerInfo(
                            recName=rec_name,
                            recType="blrec",
                            recHost=host,
                            recStatus="error",
                            recManage=manage
                        ))
    
    return servers

def create_recheme_instance(api_info: Dict, rec_name: str) -> RechemeAPI:
    """
    录播姬 API
    :param api_info: API配置信息
    :param rec_name: 实例名称
    :return: RechemeAPI实例
    """
    host = api_info.get("URL", "").rstrip('/')
    manage = api_info.get("MANAGE", True)
    basic_auth = config.get("RECHEME_BASIC", False)
    username = config.get("RECHEME_BASIC_USER", "")
    password = config.get("RECHEME_BASIC_PASS", "")
    
    return RechemeAPI(
        host=host,
        name=rec_name,
        basic_auth=basic_auth,
        username=username,
        password=password,
        manage=manage
    )

def create_blrec_instance(api_info: Dict, name: str) -> BLRECAPI:
    """
    BLREC API
    :param api_info: API配置信息
    :param name: 实例名称
    :return: BLRECAPI实例
    """
    host = api_info.get("URL", "").rstrip('/')
    
    api_key = api_info.get("BASIC_KEY", "")
    if not api_key and "BLREC_BASIC" in config and config["BLREC_BASIC"]:
        api_key = config.get("BLREC_BASIC_KEY", "bili2233")
        
    manage = api_info.get("MANAGE", True)
    
    return BLRECAPI(host, name, api_key, manage)

def handle_operation_error(operation: str, recType: str, recName: str = None, user: str = None) -> str:
    """处理错误"""
    base_msg = f"{operation}失败"
    user_info = f"用户 {user} " if user else ""
    if recName:
        return f"{user_info}在{recType}录播机 {recName} 中{base_msg}"
    return f"{user_info}{base_msg}"

@app.get("/api/room")
async def get_rooms(recType: str = None):
    """API_获取所有直播间信息"""
    if recType:
        logger.debug(f"[API] 指定录播类型: {recType}")

    rooms = []
    
    if (not recType or recType == "recheme") and "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    recheme = create_recheme_instance(api_info, rec_name)
                    rooms.extend(recheme.get_rooms())
    
    if (not recType or recType == "blrec") and "BLREC" in config:
        for rec_name, api_info_list in config["BLREC"].items():
            if isinstance(api_info_list, list) and rec_name not in ["BLREC_BASIC", "BLREC_BASIC_KEY"]:
                for api_info in api_info_list:
                    blrec = create_blrec_instance(api_info, rec_name)
                    rooms.extend(blrec.get_rooms())

    return rooms

@app.post("/api/room")
@requires_auth
async def create_room(
    request: CreateRoomRequest,
    current_user: str = Depends(get_current_user)
):
    """
    创建新的直播间
    """
    logger.debug(f"[API] 用户 {current_user} 请求创建新的直播间: {request.roomId}")
    
    try:
        if request is None or request.roomId is None:
            raise HTTPException(status_code=422, detail="缺少必要参数：roomId")
        
        logger.debug(f"[API] 请求创建房间ID为 {request.roomId} 的直播间")
        
        recType = request.recType if hasattr(request, 'recType') else None
        recName = request.recName if hasattr(request, 'recName') else None
        
        if recName:
            logger.debug(f"[API] 指定录播机实例: {recName}")
        elif recType:
            logger.debug(f"[API] 指定录播机类型: {recType}")
            
        return await _create_single_room(request, recType, recName, current_user)
    
    except Exception as e:
        logger.error(f"[API] 创建房间失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建房间失败: {str(e)}")

@app.post("/api/room/batch")
@requires_auth
async def batch_create_rooms(
    request: BatchCreateRoomRequest,
    current_user: str = Depends(get_current_user)
):
    """
    批量创建直播间
    """
    logger.debug(f"[API] 用户 {current_user} 请求批量创建直播间")
    logger.debug(f"[API] 请求批量创建 {len(request.rooms)} 个直播间")
    recType = request.recType
    recName = request.recName
    all_results = []
    
    for room_request in request.rooms:
        try:
            result = await _create_single_room(room_request, recType, recName, current_user)
            if result:
                all_results.extend(result.get("data", []))
        except HTTPException as e:
            logger.error(f"[API] 创建房间 {room_request.roomId} 失败: {e.detail}")
            continue
    
    if not all_results:
        error_msg = handle_operation_error("批量创建直播间", recType or "所有", recName, current_user)
        raise HTTPException(status_code=500, detail=error_msg)
    
    return {"data": all_results}

async def _create_single_room(request: CreateRoomRequest, recType: str = None, recName: str = None, current_user: str = None):
    """创建单个房间"""
    success_results = []
    
    if recName:
        if "RECHEME" in config and any(recName == name for name in config["RECHEME"]):
            recType = "recheme"
        elif "BLREC" in config and any(recName == name for name in config["BLREC"]):
            recType = "blrec"
    
    if (not recType or recType == "recheme") and "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if recName and rec_name != recName:
                continue
            
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    recheme = create_recheme_instance(api_info, rec_name)
                    result = recheme.create_room(request.roomId, request.autoRecord)
                    if result:
                        success_results.append(result)
    
    if (not recType or recType == "blrec") and "BLREC" in config:
        for rec_name, api_info_list in config["BLREC"].items():
            if recName and rec_name != recName:
                continue
                
            if isinstance(api_info_list, list) and rec_name not in ["BLREC_BASIC", "BLREC_BASIC_KEY"]:
                for api_info in api_info_list:
                    blrec = create_blrec_instance(api_info, rec_name)
                    result = blrec.create_room(request.roomId)
                    if result:
                        success_results.append(result)
    
    if not success_results:
        error_msg = handle_operation_error("创建直播间", recType or "所有", recName, current_user)
        log_print(f"[API] {error_msg}", "ERROR")
        raise HTTPException(status_code=500, detail=error_msg)
    
    return {"data": success_results}

@app.delete("/api/room/{roomId}")
@requires_auth
async def delete_room(
    roomId: int,
    recType: str = "recheme",
    recName: str = None,
    current_user: str = Depends(get_current_user)
):
    """
    删除房间
    """
    logger.debug(f"[API] 用户 {current_user} 请求删除房间 {roomId}")
    return await _delete_single_room(roomId, recType, recName, current_user)

@app.delete("/api/room/batch")
@requires_auth
async def batch_delete_rooms(
    request: BatchDeleteRoomRequest,
    current_user: str = Depends(get_current_user)
):
    """
    批量删除房间
    """
    logger.debug(f"[API] 用户 {current_user} 请求批量删除房间")
    logger.debug(f"[API] 请求批量删除 {len(request.rooms)} 个直播间")
    
    all_results = []
    failed_rooms = []
    
    for room_request in request.rooms:
        try:
            result = await _delete_single_room(
                room_request.roomId,
                room_request.recType,
                room_request.recName,
                current_user
            )
            if result and "data" in result:
                all_results.extend(result["data"])
        except HTTPException as e:
            failed_rooms.append({
                "roomId": room_request.roomId,
                "recType": room_request.recType,
                "recName": room_request.recName,
                "error": e.detail
            })
            logger.error(f"[API] 删除房间 {room_request.roomId} 失败: {e.detail}")
            continue
    
    return {
        "success": len(all_results) > 0,
        "total": len(request.rooms),
        "succeeded": len(all_results),
        "failed": len(failed_rooms),
        "data": all_results,
        "errors": failed_rooms if failed_rooms else None
    }

async def _delete_single_room(roomId: int, recType: str = None, recName: str = None, current_user: str = None):
    """删除单个房间"""
    logger.debug(f"[API] 请求删除房间ID为 {roomId} 的直播间")
    if recName:
        logger.debug(f"[API] 指定录播机实例: {recName}")
    
    success_results = []
    
    if recName:
        if "RECHEME" in config and any(recName == name for name in config["RECHEME"]):
            recType = "recheme"
        elif "BLREC" in config and any(recName == name for name in config["BLREC"]):
            recType = "blrec"
    
    if (not recType or recType == "recheme") and "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if recName and rec_name != recName:
                continue
            
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    recheme = create_recheme_instance(api_info, rec_name)
                    result = recheme.delete_room(roomId)
                    if result:
                        success_results.append({
                            "roomid": roomId,
                            "recServer": {
                                "recName": rec_name,
                                "recType": "recheme",
                                "recHost": api_info["URL"],
                                "recManage": api_info.get("MANAGE", True)
                            }
                        })
    
    if (not recType or recType == "blrec") and "BLREC" in config:
        for rec_name, api_info_list in config["BLREC"].items():
            if recName and rec_name != recName:
                continue
            
            if isinstance(api_info_list, list) and rec_name not in ["BLREC_BASIC", "BLREC_BASIC_KEY"]:
                for api_info in api_info_list:
                    blrec = create_blrec_instance(api_info, rec_name)
                    result = blrec.delete_room(str(roomId))
                    if result is not None:
                        success_results.append({
                            "roomid": roomId,
                            "recServer": {
                                "recName": rec_name,
                                "recType": "blrec",
                                "recHost": api_info["URL"],
                                "recManage": api_info.get("MANAGE", True)
                            }
                        })
    
    if not success_results:
        error_msg = handle_operation_error("删除直播间", recType or "所有", recName, current_user)
        raise HTTPException(status_code=500, detail=error_msg)
    
    return {"data": success_results}

@app.get("/api/room/{roomId:int}")
async def get_room_by_id(roomId: int, recType: str = None):
    """获取指定房间的数据"""
    logger.debug(f"[API] 请求获取房间ID为 {roomId} 的数据")
    if recType and recType not in ["recheme", "blrec"]:
        raise HTTPException(status_code=400, detail="不支持的录播类型")

    room_data = []
    
    if recType in [None, "recheme"] and "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    recheme = create_recheme_instance(api_info, rec_name)
                    data = recheme.get_room(roomId)
                    if data:
                        room_data.append(data)
    
    if recType in [None, "blrec"] and "BLREC" in config:
        for rec_name, api_info_list in config["BLREC"].items():
            if isinstance(api_info_list, list) and rec_name not in ["BLREC_BASIC", "BLREC_BASIC_KEY"]:
                for api_info in api_info_list:
                    blrec = create_blrec_instance(api_info, rec_name)
                    data = blrec.get_room(str(roomId))
                    if data:
                        room_data.append(data)

    if not room_data:
        error_msg = {
            "recheme": "录播姬不存在该直播间",
            "blrec": "BLREC不存在该直播间"
        }.get(recType, "不存在该直播间")
        raise HTTPException(status_code=404, detail=error_msg)
    
    return {"data": room_data}

@app.post("/api/room/{roomId}/config")
@requires_auth
async def update_room_config(
    roomId: int,
    request: RoomConfigRequest,
    recType: str = "recheme",
    recName: str = None,
    current_user: str = Depends(get_current_user)
):
    """更新房间配置"""
    logger.debug(f"[API] 用户 {current_user} 请求更新房间 {roomId} 的配置")
    logger.debug(f"[API] 请求修改房间ID为 {roomId} 的设置")
    if recName:
        logger.debug(f"[API] 指定录播姬实例: {recName}")
    
    if recType != "recheme":
        raise HTTPException(status_code=400, detail="当前只支持录播姬配置修改")
    
    success_results = []
    if "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if recName and rec_name != recName:
                continue
                
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    recheme = create_recheme_instance(api_info, rec_name)
                    result = recheme.update_room_config(roomId, request.dict())
                    if result:
                        success_results.append(result)
    
    if not success_results:
        error_msg = handle_operation_error("修改房间设置", recType, recName, current_user)
        raise HTTPException(status_code=500, detail=error_msg)
    
    return {"data": success_results}

@app.post("/api/room/{roomId}/start")
@requires_auth
async def start_room_recording(
    roomId: int,
    recType: str = "recheme",
    recName: str = None,
    current_user: str = Depends(get_current_user)
):
    """开始录制"""
    logger.debug(f"[API] 用户 {current_user} 请求开始录制房间 {roomId}")
    if recName:
        logger.debug(f"[API] 指定录播姬实例: {recName}")
    
    if recType != "recheme":
        raise HTTPException(status_code=400, detail="当前只支持录播姬录制")
    
    success_results = []
    if "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if recName and rec_name != recName:
                continue

            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    recheme = create_recheme_instance(api_info, rec_name)
                    result = recheme.start_recording(roomId)
                    if result:
                        success_results.append(result)

    if not success_results:
        error_msg = handle_operation_error("开始录制", recType, recName, current_user)
        raise HTTPException(status_code=500, detail=error_msg)
    
    return {"data": success_results}

@app.post("/api/room/{roomId}/stop")
@requires_auth
async def stop_room_recording(
    roomId: int,
    recType: str = "recheme",
    recName: str = None,
    current_user: str = Depends(get_current_user)
):
    """停止录制"""
    logger.debug(f"[API] 请求停止录制房间ID为 {roomId} 的直播")
    if recName:
        logger.debug(f"[API] 指定录播姬实例: {recName}")
    
    if recType != "recheme":
        raise HTTPException(status_code=400, detail="当前只支持录播姬录制")
    
    success_results = []
    if "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if recName and rec_name != recName:
                continue
                
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    recheme = create_recheme_instance(api_info, rec_name)
                    result = recheme.stop_recording(roomId)
                    if result:
                        success_results.append(result)
    
    if not success_results:
        error_msg = handle_operation_error("停止录制", recType, recName, current_user)
        raise HTTPException(status_code=500, detail=error_msg)
    
    return {"data": success_results}

@app.post("/api/room/{roomId}/split")
@requires_auth
async def split_room_recording(
    roomId: int,
    recType: str = "recheme",
    recName: str = None,
    current_user: str = Depends(get_current_user)
):
    """手动分段"""
    logger.debug(f"[API] 用户 {current_user} 请求手动分段房间 {roomId}")
    if recName:
        logger.debug(f"[API] 指定录播姬实例: {recName}")
    
    if recType != "recheme":
        raise HTTPException(status_code=400, detail="当前只支持录播姬分段")
    
    success_results = []
    if "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if recName and rec_name != recName:
                continue
                
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    recheme = create_recheme_instance(api_info, rec_name)
                    result = recheme.split_recording(roomId)
                    if result:
                        success_results.append(result)
    
    if not success_results:
        error_msg = handle_operation_error("手动分段", recType, recName, current_user)
        raise HTTPException(status_code=500, detail=error_msg)
    
    return {"data": success_results}

@app.post("/api/room/{roomId}/refresh")
@requires_auth
async def refresh_room(
    roomId: int,
    recType: str = "recheme",
    recName: str = None,
    current_user: str = Depends(get_current_user)
):
    """刷新房间信息"""
    logger.debug(f"[API] 用户 {current_user} 请求刷新房间 {roomId}")
    if recName:
        logger.debug(f"[API] 指定录播姬实例: {recName}")
    
    if recType != "recheme":
        raise HTTPException(status_code=400, detail="当前只支持录播姬刷新")
    
    success_results = []
    if "RECHEME" in config:
        for rec_name, api_info_list in config["RECHEME"].items():
            if recName and rec_name != recName:
                continue
                
            if isinstance(api_info_list, list):
                for api_info in api_info_list:
                    recheme = create_recheme_instance(api_info, rec_name)
                    result = recheme.refresh_room(roomId)
                    if result:
                        success_results.append(result)
    
    if not success_results:
        error_msg = handle_operation_error("刷新房间信息", recType, recName, current_user)
        raise HTTPException(status_code=500, detail=error_msg)
    
    return {"data": success_results}

async def _add_single_server(request: AddServerRequest, save_immediately: bool = True, current_user: str = None) -> Dict:
    """添加单个录播机"""
    logger.debug(f"[API] {'用户 ' + current_user + ' ' if current_user else ''}请求添加新的录播机: {request.recName} ({request.recType})")
    
    if request.recType not in ["recheme", "blrec"]:
        raise HTTPException(status_code=400, detail="不支持的录播类型，必须是 recheme 或 blrec")
    
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL 必须以 http:// 或 https:// 开头")
    
    global config
    if not config:
        config = load_config()
    
    if (request.recType == "recheme" and "RECHEME" in config and request.recName in config["RECHEME"]) or \
       (request.recType == "blrec" and "BLREC" in config and request.recName in config["BLREC"]):
        raise HTTPException(status_code=400, detail=f"录播机名称 {request.recName} 已存在")
    
    server_config = {
        "URL": request.url
    }
    
    if request.manage is not True:
        server_config["MANAGE"] = request.manage
    
    if request.recType == "recheme":
        if request.basic is not None:
            server_config["BASIC"] = request.basic
            
        if request.basicUser:
            server_config["BASIC_USER"] = request.basicUser
            
        if request.basicPass:
            server_config["BASIC_PASS"] = request.basicPass
            
    elif request.recType == "blrec":
        if request.basicKey:
            server_config["BASIC_KEY"] = request.basicKey
    
    if request.recType == "recheme":
        if "RECHEME" not in config:
            config["RECHEME"] = {}
        if request.recName not in config["RECHEME"]:
            config["RECHEME"][request.recName] = []
        config["RECHEME"][request.recName].append(server_config)
    else:
        if "BLREC" not in config:
            config["BLREC"] = {}
        if request.recName not in config["BLREC"]:
            config["BLREC"][request.recName] = []
        config["BLREC"][request.recName].append(server_config)
    
    if save_immediately and not save_config(config):
        raise HTTPException(status_code=500, detail="保存配置文件失败")
    
    response_data = {
        "recName": request.recName,
        "recType": request.recType,
        "recHost": request.url,
        "recStatus": "未知",
        "recManage": request.manage
    }
    
    logger.debug(f"[API] 成功添加录播机: {request.recName}")
    return {"success": True, "data": response_data}


@app.get("/api/server", response_model=List[RecServerInfo])
async def get_recservers(
    recName: str = None,
    recType: str = None,
    recStatus: str = None
):
    """获取所有录播机信息"""
    filters = []
    if recName:
        filters.append(f"名称={recName}")
    if recType:
        filters.append(f"类型={recType}")
    if recStatus:
        filters.append(f"状态={recStatus}")
    
    if filters:
        logger.debug(f"[API] 筛选条件: {', '.join(filters)}")
    
    servers = await get_all_recservers()
    
    filtered_servers = []
    for server in servers:
        if recName and server.recName != recName:
            continue
        if recType and server.recType != recType:
            continue
        if recStatus and server.recStatus != recStatus:
            continue
        filtered_servers.append(server)
    
    return filtered_servers


@app.post("/api/server")
@requires_auth
async def add_server(
    request: Union[AddServerRequest, BatchAddServerRequest],
    current_user: str = Depends(get_current_user)
):
    """添加录播机"""
    logger.debug(f"[API] 用户 {current_user} 请求添加录播机")
    
    if hasattr(request, "servers") and request.servers:
        logger.debug(f"[API] 批量添加请求，共 {len(request.servers)} 个录播机")
        all_results = []
        failed_servers = []
        
        for server_req in request.servers:
            try:
                result = await _add_single_server(server_req, False, current_user)
                all_results.append(result["data"])
            except HTTPException as e:
                failed_servers.append({
                    "recName": server_req.recName,
                    "recType": server_req.recType,
                    "error": e.detail
                })
                logger.error(f"[API] 添加录播机 {server_req.recName} 失败: {e.detail}")
        
        if not save_config(config):
            logger.error("[API] 保存配置文件失败")
            raise HTTPException(status_code=500, detail="保存配置文件失败")
            
        logger.debug(f"[API] 批量添加完成，成功: {len(all_results)}，失败: {len(failed_servers)}")
        return {
            "success": len(all_results) > 0,
            "total": len(request.servers),
            "succeeded": len(all_results),
            "failed": len(failed_servers),
            "data": all_results,
            "errors": failed_servers if failed_servers else None
        }
    
    return await _add_single_server(request, True, current_user)



@app.delete("/api/server")
@requires_auth
async def delete_server(
    request: DeleteServerRequest,
    current_user: str = Depends(get_current_user)
):
    """删除录播机"""
    logger.debug(f"[API] 用户 {current_user} 请求删除录播机服务器: {request.recName} ({request.recType})")
    return await _delete_single_server(request.recName, request.recType, current_user)

@app.delete("/api/server/batch")
@requires_auth
async def batch_delete_servers(
    request: BatchDeleteServerRequest,
    current_user: str = Depends(get_current_user)
):
    """批量删除录播机"""
    logger.debug(f"[API] 用户 {current_user} 请求批量删除录播机服务器，共 {len(request.servers)} 个")
    
    all_results = []
    failed_servers = []
    
    for server_request in request.servers:
        try:
            result = await _delete_single_server(
                server_request.recName,
                server_request.recType,
                current_user
            )
            if result and "success" in result and result["success"]:
                all_results.append({
                    "recName": server_request.recName,
                    "recType": server_request.recType,
                    "success": True
                })
        except HTTPException as e:
            failed_servers.append({
                "recName": server_request.recName,
                "recType": server_request.recType,
                "error": e.detail
            })
            logger.error(f"[API] 删除录播机 {server_request.recName} 失败: {e.detail}")
            continue
    
    return {
        "success": len(all_results) > 0,
        "total": len(request.servers),
        "succeeded": len(all_results),
        "failed": len(failed_servers),
        "data": all_results,
        "errors": failed_servers if failed_servers else None
    }

async def _delete_single_server(recName: str, recType: str, current_user: str = None):
    """删除单个录播机"""
    if not recName:
        raise HTTPException(status_code=400, detail="录播机名称不能为空")
    
    if recType not in ["recheme", "blrec"]:
        raise HTTPException(status_code=400, detail="不支持的录播机类型")
    
    if recType == "recheme" and (recName not in config.get("RECHEME", {})):
        raise HTTPException(status_code=404, detail=f"录播姬服务器 {recName} 不存在")
    
    if recType == "blrec" and (recName not in config.get("BLREC", {})):
        raise HTTPException(status_code=404, detail=f"BLREC服务器 {recName} 不存在")
    
    try:
        if recType == "recheme":
            del config["RECHEME"][recName]
            logger.info(f"[API] 删除录播姬服务器 {recName} 成功")
        else:
            del config["BLREC"][recName]
            logger.info(f"[API] 删除BLREC服务器 {recName} 成功")
        
        save_config(config)
        
        return {
            "success": True,
            "message": f"已删除{recType}录播机 {recName}",
            "data": {
                "recName": recName,
                "recType": recType
            }
        }
    except Exception as e:
        logger.error(f"[API] 删除录播机 {recName} 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除录播机失败: {str(e)}")

@app.get("/api/login")
async def check_auth_status():
    """
    检查认证状态
    当AUTH.ENABLE为false时，返回无需认证的提示
    当AUTH.ENABLE为true时，返回需要认证的提示
    """
    auth_enabled = config.get("AUTH", {}).get("ENABLE", False)
    return {
        "message": "需要登录" if auth_enabled else "认证未启用，无需登录",
        "auth_required": auth_enabled
    }

@app.post("/api/login")
async def login(request: LoginRequest):
    username = request.username
    password = request.password
    if not config.get("AUTH", {}).get("ENABLE", False):
        return {
            "message": "认证未启用，无需登录",
            "token": None,
            "auth_required": False
        }
    if auth.authenticate_user(username, password):
        token = auth.create_token(username)
        return {
            "message": "登录成功",
            "token": token,
            "auth_required": True
        }
    
    raise HTTPException(
        status_code=401,
        detail="用户名或密码错误"
    )

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    return FileResponse("web/favicon.ico")

@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg():
    return FileResponse("web/favicon.svg")

@app.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_spa(full_path: str):
    # 排除API路径
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    
    try:
        with open("web/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"[前端] 加载前端页面失败: {e}")
        return f"<html><body><h1>前端加载失败</h1><p>{str(e)}</p></body></html>"

if __name__ == "__main__":
    try:
        config = load_config()
        uvicorn.run(
            "main:app",
            host=config["HOST"],
            port=config["PORT"],
            log_level="info",
        )
    except Exception as e:
        log_print(f"启动失败: {e}", "ERROR")
        sys.exit(1)