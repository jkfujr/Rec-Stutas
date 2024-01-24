import os
import sys
import yaml
import base64
import requests
import uvicorn
import logging
from logging.handlers import TimedRotatingFileHandler
from typing import List, Dict
from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from concurrent.futures import ThreadPoolExecutor, as_completed


### 日志模块
# 获取所在的目录
script_directory = os.path.dirname(__file__)
log_directory = os.path.join(script_directory, "logs")
os.makedirs(log_directory, exist_ok=True)

# 配置日志记录器
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] - %(message)s")
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# 按日期分割日志文件并保留30天
log_file_handler = TimedRotatingFileHandler(
    os.path.join(log_directory, "log.log"),
    when="D",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)
log_file_handler.setFormatter(log_formatter)
if not logger.handlers:
    logger.addHandler(log_file_handler)


### 配置文件模块
# 读取配置文件
def load_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
        logger.debug("配置文件读取成功")
    except FileNotFoundError:
        logger.error("配置文件不存在")
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.error(f"解析配置文件时出现问题: {e}")
        sys.exit(1)

    # 配置读取
    config["HOST"] = config.get("HOST", "127.0.0.1")
    config["PORT"] = int(config.get("PORT", 11111))
    logger.debug(f"配置读取：HOST={config['HOST']}, PORT={config['PORT']}")

    # 默认值设置
    config.setdefault("RECHEME_BASIC", False)
    config.setdefault("RECHEME_BASIC_USER", "")
    config.setdefault("RECHEME_BASIC_PASS", "")
    config.setdefault("BLREC_BASIC", True)
    config.setdefault("BLREC_BASIC_KEY", "bili2233")


    return config


try:
    config = load_config()
except Exception as e:
    logger.error(f"加载配置文件时发生未知错误: {e}")
    sys.exit(1)


# FastAPI设置
app = FastAPI()
app.mount("/assets", StaticFiles(directory="./webui/assets"), name="assets")
templates = Jinja2Templates(directory="webui")


### 一些全局变量
# 配置文件
config = load_config()
# 数据缓存
cached_data = None
# 全局Session对象
session = requests.Session()


# 根据API信息构建请求头
def build_request_headers(api_info: Dict) -> Dict:
    headers = {}
    rectype = api_info["rectpye"]

    if rectype == "blrec":
        api_key = api_info.get(
            "BASIC_KEY", config.get("BLREC", {}).get("BLREC_BASIC_KEY", "")
        )
        headers["x-api-key"] = api_key
        logger.debug("BLREC请求头构建完毕: %s", api_key)
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
            logger.debug("录播姬请求头构建完毕: %s", auth_str)

    return headers


# 请求所有直播间的数据
def fetch_api_data(api_info: Dict) -> List[Dict]:
    """
    请求所有直播间的数据。
    :param api_info: 包含API详细信息的字典。
    :return: 从API获取的数据列表。
    """
    url = (
        f"{api_info['URL']}/api/room"
        if api_info["rectpye"] == "recheme"
        else f"{api_info['URL']}/api/v1/tasks/data"
    )
    logger.debug(f"请求API URL: {url}")

    headers = build_request_headers(api_info)

    try:
        response = session.get(url, headers=headers, timeout=3)
        logger.debug(f"响应状态码: {response.status_code}, URL: {url}")

        if response.status_code == 200:
            data = response.json()
            logger.debug(f"获取到的数据数量: {len(data)}, URL: {url}")

            for item in data:
                item.update(
                    {"rectpye": api_info["rectpye"], "base_url": api_info["URL"]}
                )
            return data
        else:
            logger.error(f"请求失败, 状态码: {response.status_code}, URL: {url}")
            return []
    except requests.exceptions.Timeout:
        logger.error(f"请求超时, URL: {url}")
        return []
    except Exception as e:
        logger.error(f"发生异常: {e}, URL: {url}")
        return []


# 请求特定直播间的数据
def fetch_room_data(room_id: str, rectpye: str = None) -> List[Dict]:
    """
    请求特定直播间的数据。
    :param room_id: 直播间ID。
    :param rectpye: 数据类型（recheme或blrec）。
    :return: 直播间数据列表。
    """
    room_data = []
    for data in cached_data:
        if rectpye is None or data["rectpye"] == rectpye:
            if data["rectpye"] == "recheme" and str(data.get("roomId")) == room_id:
                url = f"{data['base_url']}/api/room/{room_id}"
            elif (
                data["rectpye"] == "blrec"
                and str(data.get("room_info", {}).get("room_id")) == room_id
            ):
                url = f"{data['base_url']}/api/v1/tasks/{room_id}/data"
            else:
                continue

            logger.debug(f"请求单条数据URL: {url}")

            headers = build_request_headers({"rectpye": data["rectpye"]})

            response = session.get(url, headers=headers)
            if response.status_code == 200:
                single_room_data = response.json()
                single_room_data.update(
                    {"rectpye": data["rectpye"], "base_url": data["base_url"]}
                )
                room_data.append(single_room_data)
            else:
                logger.error(f"请求失败: {url}, 状态码: {response.status_code}")
    return room_data


# API数据请求
def fetch_data() -> List[Dict]:
    all_data = []
    for rectype, apis in config.items():
        if rectype in ["RECHEME", "BLREC"]:
            for api_key, api_info_list in apis.items():
                if isinstance(api_info_list, list):
                    for api_info in api_info_list:
                        api_info.update({"rectpye": rectype.lower()})
                        logger.debug(f"开始获取数据, API信息: {api_info}")
                        api_data = fetch_api_data(api_info)
                        all_data.extend(api_data)
                        logger.debug(f"已获取数据, 数据数量: {len(api_data)}")

    logger.debug(f"总数据量: {len(all_data)}")
    return all_data


# webui端点
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# 获取所有数据
@app.get("/api/data")
async def get_all_data():
    logger.info(f'调用路径 @app.get("/api/data")')
    global cached_data
    logger.debug(f"请求获取所有数据")
    cached_data = fetch_data()
    return {"data": cached_data}


# 获取指定直播间数据
@app.get("/api/data/{roomId:int}")
async def get_room_by_id(roomId: int):
    logger.info(f'调用路径 @app.get("/api/data/{roomId}")')
    logger.debug(f"请求获取房间ID为 {roomId} 的数据")
    room_data = fetch_room_data(str(roomId))
    if not room_data:
        logger.error(f"不存在该直播间")
        raise HTTPException(status_code=404, detail="不存在该直播间")
    return {"data": room_data}


# 获取 recheme 所有数据
@app.get("/api/data/recheme")
async def get_recheme_data():
    logger.info(f'调用路径 @app.get("/api/data/recheme")')
    global cached_data
    logger.debug(f"请求获取 recheme 类型的所有数据")
    cached_data = fetch_data()
    recheme_data = [d for d in cached_data if d["rectpye"] == "recheme"]
    logger.debug(f"获取到的 recheme 数据数量: {len(recheme_data)}")
    return {"data": recheme_data}


# 获取 blrec 所有数据
@app.get("/api/data/blrec")
async def get_blrec_data():
    logger.info(f'调用路径 @app.get("/api/data/blrec")')
    global cached_data
    logger.debug(f"请求获取 blrec 类型的所有数据")
    cached_data = fetch_data()
    blrec_data = [d for d in cached_data if d["rectpye"] == "blrec"]
    logger.debug(f"获取到的 blrec 数据数量: {len(blrec_data)}")
    return {"data": blrec_data}


# 获取 recheme 指定数据
@app.get("/api/data/recheme/{roomId:int}")
async def get_recheme_room_by_id(roomId: int):
    logger.info(f'调用路径 @app.get("/api/data/recheme/{roomId}")')
    logger.debug(f"请求获取 recheme 类型房间ID为 {roomId} 的数据")
    recheme_room_data = fetch_room_data(str(roomId), "recheme")
    if not recheme_room_data:
        logger.error(f"录播姬中不存在该直播间")
        raise HTTPException(status_code=404, detail="录播姬中不存在该直播间")
    return {"data": recheme_room_data}


# 获取 blrec 指定数据
@app.get("/api/data/blrec/{roomId:int}")
async def get_blrec_room_by_id(roomId: int):
    logger.info(f'调用路径 @app.get("/api/data/blrec/{roomId}")')
    logger.debug(f"请求获取 blrec 类型房间ID为 {roomId} 的数据")
    blrec_room_data = fetch_room_data(str(roomId), "blrec")
    if not blrec_room_data:
        logger.error(f"BLREC中不存在该直播间")
        raise HTTPException(status_code=404, detail="BLREC中不存在该直播间")
    return {"data": blrec_room_data}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config["HOST"],
        port=config["PORT"],
        log_level="info",
        reload=True,
    )
