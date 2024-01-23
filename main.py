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
# 日志文件夹路径和日志文件名
log_folder = "logs"
log_file_path = os.path.join(os.path.dirname(__file__), log_folder, "log.log")

# 确保日志文件夹存在
if not os.path.exists(log_folder):
    os.makedirs(log_folder)

# 创建日志记录器
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# 文件处理器，保留30天的日志
file_handler = TimedRotatingFileHandler(
    log_file_path, when="midnight", interval=1, encoding="utf-8", backupCount=30
)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
file_handler.setLevel(logging.DEBUG)
file_handler.suffix = "%Y-%m-%d.log"
logger.addHandler(file_handler)

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
logger.addHandler(console_handler)


### 配置文件模块
# 读取配置文件
def load_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except FileNotFoundError:
        logger.error("配置文件不存在")
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.error(f"解析配置文件时出现问题: {e}")
        sys.exit(1)

    # 全局默认值
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


app = FastAPI()
app.mount("/assets", StaticFiles(directory="./webui/assets"), name="assets")
templates = Jinja2Templates(directory="webui")


cached_data = None


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


def fetch_api_data(api_info: Dict) -> List[Dict]:
    url = (
        f"{api_info['URL']}/api/room"
        if api_info["rectpye"] == "recheme"
        else f"{api_info['URL']}/api/v1/tasks/data"
    )
    logger.debug(f"请求API URL: {url}")
    try:
        response = requests.get(url, headers=get_headers(api_info), timeout=3)
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


# 处理不同类型的房间ID
def fetch_room_data(room_id: str, rectpye: str = None) -> List[Dict]:
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
            response = requests.get(
                url, headers=get_headers({"rectpye": data["rectpye"]})
            )
            if response.status_code == 200:
                single_room_data = response.json()
                single_room_data.update(
                    {"rectpye": data["rectpye"], "base_url": data["base_url"]}
                )
                room_data.append(single_room_data)
            else:
                logger.error(f"请求失败: {url}, 状态码: {response.status_code}")
    return room_data


# 请求头
def get_headers(api_info: Dict) -> Dict:
    headers = {}
    rectype = api_info["rectpye"]

    if rectype == "blrec":
        api_key = api_info.get(
            "BASIC_KEY", config.get("BLREC", {}).get("BLREC_BASIC_KEY", "")
        )
        headers["x-api-key"] = api_key
        logger.debug(f"BLREC请求头: {api_key}")
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
            logger.debug(f"录播姬请求头: {auth_str}")

    return headers


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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
        host="0.0.0.0",
        port=11111,
        log_level="info",
        reload=True,
    )
