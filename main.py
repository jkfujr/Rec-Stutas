import os,sys,yaml,base64,requests,uvicorn,logging
from typing import List, Dict
from logging.handlers import TimedRotatingFileHandler
from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

### 全局变量
# 数据缓存
cached_data = None
# 全局 Session 对象
session = requests.Session()
# fastapi
app = FastAPI()


### 日志模块
def log():
    global logger
    # 检查是否已经配置了处理器
    if logging.getLogger().handlers:
        return logging.getLogger()

    # 获取目录
    script_directory = os.path.dirname(os.path.abspath(__file__))
    log_directory = os.path.join(script_directory, "logs")
    if not os.path.exists(log_directory):
        os.makedirs(log_directory)

    # 日志格式
    log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(processName)s - %(message)s"
    )

    # 日志名称和后缀
    default_log_file_name = "rs"
    log_file_path = os.path.join(log_directory, default_log_file_name)

    # 创建日志文件处理器,每天分割日志文件
    log_file_handler = TimedRotatingFileHandler(
        log_file_path,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    log_file_handler.suffix = "%Y-%m-%d.log"
    log_file_handler.setFormatter(log_formatter)

    # 创建并配置 logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(log_file_handler)

    return logger


logger = log()


### 合并日志与打印信息
def log_print(message, prefix="", level="INFO"):
    """
    用法
    log_print("信息", "等级:     ", "等级")
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    # 日志
    logger = logging.getLogger()
    logger.log(level, message)
    # 打印
    print(prefix + message)


### 配置文件模块
# 读取配置文件
def load_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
        log_print("[配置] 配置文件读取成功", "INFO:     ", "INFO")
    except FileNotFoundError:
        log_print("[配置] 配置文件不存在", "ERROR:     ", "ERROR")
        sys.exit(1)
    except yaml.YAMLError as e:
        log_print(f"[配置] 解析配置文件时出现问题: {e}", "ERROR:     ", "ERROR")
        sys.exit(1)

    # 默认值设置
    config.setdefault("HOST", "127.0.0.1")
    config.setdefault("PORT", 11111)
    config.setdefault("RECHEME_BASIC", False)
    config.setdefault("RECHEME_BASIC_USER", "")
    config.setdefault("RECHEME_BASIC_PASS", "")
    config.setdefault("BLREC_BASIC", True)
    config.setdefault("BLREC_BASIC_KEY", "bili2233")

    return config


try:
    config = load_config()
except Exception as e:
    log_print(f"[配置] 加载配置文件时发生未知错误: {e}", "ERROR:     ", "ERROR")
    sys.exit(1)


# 根据API信息构建请求头
def build_request_headers(api_info: Dict) -> Dict:
    headers = {}
    rectype = api_info["rec_tpye"]

    if rectype == "blrec":
        api_key = api_info.get(
            "BASIC_KEY", config.get("BLREC", {}).get("BLREC_BASIC_KEY", "")
        )
        headers["x-api-key"] = api_key
        logger.debug("[请求] BLREC请求头构建完毕: %s", api_key)
    elif rectype == "recheme":
        if api_info.get("BASIC", config.get("RECHEME", {}).get("RECHEME_BASIC", False)):
            user = api_info.get(
                "BASIC_USER", config.get("RECHEME", {}).get("RECHEME_BASIC_USER", "")
            )
            password = api_info.get(
                "BASIC_PASS", config.get("RECHEME", {}).get("RECHEME_BASIC_PASS", "")
            )
            auth_str = f"{user}:{password}"
            encoded_credentials = base64.b64encode(auth_str.encode("utf-8")).decode(
                "utf-8"
            )
            headers["Authorization"] = f"Basic {encoded_credentials}"
            logger.debug("[请求] 录播姬请求头构建完毕: %s", auth_str)

    return headers


# 请求API返回数据
def perform_api_request(url: str, headers: Dict) -> List[Dict]:
    """
    执行对 API 的请求并返回数据。
    :param url: API的URL地址。
    :param headers: 请求头。
    :return: API返回的数据列表。
    """
    try:
        response = session.get(url, headers=headers, timeout=3)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                logger.debug(f"[请求] 从 {url} 获取到数据量: {len(data)}")
            elif isinstance(data, dict):
                logger.debug(f"[请求] 从 {url} 获取到数据量: 1")
            return data
        else:
            log_print(
                f"[请求] 请求失败，状态码: {response.status_code}, URL: {url}",
                "ERROR:     ",
                "ERROR",
            )
            return []
    except requests.exceptions.Timeout:
        log_print(f"[请求] 请求超时, URL: {url}", "ERROR:     ", "ERROR")
        return []
    except Exception as e:
        log_print(f"[请求] 请求异常: {e}, URL: {url}", "ERROR:     ", "ERROR")
        return []


# 请求所有直播间的数据
def fetch_api_data(api_info: Dict, rec_name: str) -> List[Dict]:
    """
    请求所有直播间的数据。
    :param api_info: 包含API详细信息的字典。
    :param rec_name: API的名称，如'REC001'。
    :return: 从API获取的数据列表。
    """
    url = (
        f"{api_info['URL']}/api/room"
        if api_info["rec_tpye"] == "recheme"
        else f"{api_info['URL']}/api/v1/tasks/data"
    )
    headers = build_request_headers(api_info)
    api_data = perform_api_request(url, headers)

    for item in api_data:
        item.update(
            {
                "rec_name": rec_name,
                "rec_tpye": api_info["rec_tpye"],
                "rec_url": api_info["URL"],
            }
        )
    return api_data


# 请求特定直播间的数据
def fetch_room_data(room_id: str, rec_tpye: str = None) -> List[Dict]:
    """
    请求特定直播间的数据。
    :param room_id: 直播间ID。
    :param rec_tpye: 数据类型（recheme或blrec）。
    :return: 直播间数据列表。
    """
    global cached_data

    if cached_data is None:
        log_print("[请求] 缓存数据为空，正在重新获取所有数据", "WARN:     ", "WARN")
        # logger.warning("[请求] 缓存数据为空，正在重新获取所有数据")
        cached_data = fetch_data()

    room_data = []
    for data in cached_data:
        if rec_tpye is None or data["rec_tpye"] == rec_tpye:
            if data["rec_tpye"] == "recheme" and str(data.get("roomId")) == room_id:
                url = f"{data['rec_url']}/api/room/{room_id}"
            elif (
                data["rec_tpye"] == "blrec"
                and str(data.get("room_info", {}).get("room_id")) == room_id
            ):
                url = f"{data['rec_url']}/api/v1/tasks/{room_id}/data"
            else:
                continue

            headers = build_request_headers({"rec_tpye": data["rec_tpye"]})
            single_room_data = perform_api_request(url, headers)
            if single_room_data:
                single_room_data.update(
                    {
                        "rec_name": data["rec_name"],
                        "rec_tpye": data["rec_tpye"],
                        "rec_url": data["rec_url"],
                    }
                )
                room_data.append(single_room_data)

                logger.debug(f"[请求] 获取到的直播间数据: {single_room_data}")

    return room_data


# API数据请求
def fetch_data() -> List[Dict]:
    all_data = []
    for rectype, apis in config.items():
        if rectype in ["RECHEME", "BLREC"]:
            for rec_name, api_info_list in apis.items():
                if isinstance(api_info_list, list):
                    for api_info in api_info_list:
                        api_info.update({"rec_tpye": rectype.lower()})
                        logger.debug(f"[请求] 开始获取数据, API信息: {api_info}")
                        api_data = fetch_api_data(api_info, rec_name)
                        all_data.extend(api_data)
                        logger.debug(f"[请求] 已获取数据量: {len(api_data)}")

    logger.debug(f"[请求] 总数据量: {len(all_data)}")
    return all_data


# webui设置
app.mount("/assets", StaticFiles(directory="./webui/assets"), name="assets")
templates = Jinja2Templates(directory="webui")


# webui路径
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# 录播姬cli启动命令生成
@app.get("/rechemetool", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("recheme.html", {"request": request})


# APi_获取所有数据
@app.get("/api/data")
async def get_all_data():
    logger.debug("[API] 请求获取所有数据")
    # logger.debug('[API] 请求获取所有数据')
    logger.debug(f'[API] 调用路径 @app.get("/api/data")')
    global cached_data
    cached_data = fetch_data()
    return {"data": cached_data}


# APi_获取指定直播间数据
@app.get("/api/data/{roomId:int}")
async def get_room_by_id(roomId: int):
    logger.debug(f"[API] 请求获取房间ID为 {roomId} 的数据")
    logger.debug(f'[API] 调用路径 @app.get("/api/data/{roomId}")')
    room_data = fetch_room_data(str(roomId))
    if not room_data:
        log_print("[API] 不存在该直播间", "ERROR:     ", "ERROR")
        raise HTTPException(status_code=404, detail="不存在该直播间")
    return {"data": room_data}


# APi_获取 录播姬 所有数据
@app.get("/api/data/recheme")
async def get_recheme_data():
    logger.debug("[API] 请求获取 recheme 类型的所有数据")
    logger.debug('[API] 调用路径 @app.get("/api/data/recheme")')
    global cached_data
    cached_data = fetch_data()
    recheme_data = [d for d in cached_data if d["rec_tpye"] == "recheme"]
    logger.debug(f"[API] 获取到的 recheme 数据量: {len(recheme_data)}")
    return {"data": recheme_data}


# APi_获取 blrec 所有数据
@app.get("/api/data/blrec")
async def get_blrec_data():
    logger.debug("[API] 请求获取 blrec 类型的所有数据")
    logger.debug('[API] 调用路径 @app.get("/api/data/blrec")')
    global cached_data
    cached_data = fetch_data()
    blrec_data = [d for d in cached_data if d["rec_tpye"] == "blrec"]
    logger.debug(f"[API] 获取到的 blrec 数据量: {len(blrec_data)}")
    return {"data": blrec_data}


# APi_获取 录播姬 指定数据
@app.get("/api/data/recheme/{roomId:int}")
async def get_recheme_room_by_id(roomId: int):
    logger.debug(f"[API] 请求获取 recheme 类型房间ID为 {roomId} 的数据")
    logger.debug(f'[API] 调用路径 @app.get("/api/data/recheme/{roomId}")')
    recheme_room_data = fetch_room_data(str(roomId), "recheme")
    if not recheme_room_data:
        log_print("[API] 录播姬不存在该直播间", "ERROR:     ", "ERROR")
        raise HTTPException(status_code=404, detail="录播姬不存在该直播间")
    return {"data": recheme_room_data}


# APi_获取 blrec 指定数据
@app.get("/api/data/blrec/{roomId:int}")
async def get_blrec_room_by_id(roomId: int):
    logger.debug(f"[API] 请求获取 blrec 类型房间ID为 {roomId} 的数据")
    logger.debug(f'[API] 调用路径 @app.get("/api/data/blrec/{roomId}")')
    blrec_room_data = fetch_room_data(str(roomId), "blrec")
    if not blrec_room_data:
        log_print("[API] BLREC不存在该直播间", "ERROR:     ", "ERROR")
        raise HTTPException(status_code=404, detail="BLREC不存在该直播间")
    return {"data": blrec_room_data}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config["HOST"],
        port=config["PORT"],
        log_level="info",
    )