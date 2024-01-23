import base64
import yaml
import requests
import uvicorn
from typing import List, Dict
from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from concurrent.futures import ThreadPoolExecutor, as_completed


# 读取配置文件
def load_config():
    with open("config.yaml", "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    # 全局默认值
    config.setdefault("RECHEME_BASIC", False)
    config.setdefault("RECHEME_BASIC_USER", "")
    config.setdefault("RECHEME_BASIC_PASS", "")
    config.setdefault("BLREC_BASIC", True)
    config.setdefault("BLREC_BASIC_KEY", "bili2233")

    return config


config = load_config()


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
                        print(f"[DEBUG] 开始获取数据, API信息: {api_info}")
                        api_data = fetch_api_data(api_info)
                        all_data.extend(api_data)
                        print(f"[DEBUG] 已获取数据, 数据数量: {len(api_data)}")

    print(f"[DEBUG] 总数据量: {len(all_data)}")
    return all_data


def fetch_api_data(api_info: Dict) -> List[Dict]:
    url = (
        f"{api_info['URL']}/api/room"
        if api_info["rectpye"] == "recheme"
        else f"{api_info['URL']}/api/v1/tasks/data"
    )
    print(f"[DEBUG] 请求API URL: {url}")
    try:
        response = requests.get(url, headers=get_headers(api_info), timeout=3)
        print(f"[DEBUG] 响应状态码: {response.status_code}, URL: {url}")
        if response.status_code == 200:
            data = response.json()
            print(f"[DEBUG] 获取到的数据数量: {len(data)}, URL: {url}")
            for item in data:
                item.update(
                    {"rectpye": api_info["rectpye"], "base_url": api_info["URL"]}
                )
            return data
        else:
            print(f"[ERROR] 请求失败, 状态码: {response.status_code}, URL: {url}")
            return []
    except requests.exceptions.Timeout:
        print(f"[ERROR] 请求超时, URL: {url}")
        return []
    except Exception as e:
        print(f"[ERROR] 发生异常: {e}, URL: {url}")
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

            print(f"[DEBUG] 请求单条数据URL: {url}")
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
                print(f"[ERROR] 请求失败: {url}, 状态码: {response.status_code}")
    return room_data


# 请求头
def get_headers(api_info: Dict) -> Dict:
    headers = {}
    rectype = api_info["rectpye"]

    if rectype == "blrec":
        # 使用BLREC全局设置或API特定设置
        api_key = api_info.get(
            "BASIC_KEY", config.get("BLREC", {}).get("BLREC_BASIC_KEY", "")
        )
        headers["x-api-key"] = api_key
        print(f"[DEBUG] BLREC请求头: {api_key}")
    elif rectype == "recheme":
        # 使用RECHEME全局设置或API特定设置
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
            print(f"[DEBUG] 录播姬请求头: {auth_str}")

    return headers


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/data")
async def get_all_data():
    print('[DEBUG] 调用路径 @app.get("/api/data")')
    global cached_data
    print("[DEBUG] 请求获取所有数据")
    cached_data = fetch_data()
    return {"data": cached_data}


# 获取指定直播间数据
@app.get("/api/data/{roomId:int}")
async def get_room_by_id(roomId: int):
    print('[DEBUG] 调用路径 @app.get("/api/data/{roomId:int}")')
    print(f"[DEBUG] 请求获取房间ID为 {roomId} 的数据")
    room_data = fetch_room_data(str(roomId))
    if not room_data:
        print("[ERROR] 不存在该直播间")
        raise HTTPException(status_code=404, detail="不存在该直播间")
    return {"data": room_data}


# 获取 recheme 所有数据
@app.get("/api/data/recheme")
async def get_recheme_data():
    print('[DEBUG] 调用路径 @app.get("/api/data/recheme")')
    global cached_data
    print("[DEBUG] 请求获取 recheme 类型的所有数据")
    cached_data = fetch_data()
    recheme_data = [d for d in cached_data if d["rectpye"] == "recheme"]
    print(f"[DEBUG] 获取到的 recheme 数据数量: {len(recheme_data)}")
    return {"data": recheme_data}


# 获取 blrec 所有数据
@app.get("/api/data/blrec")
async def get_blrec_data():
    print('[DEBUG] 调用路径 @app.get("/api/data/blrec")')
    global cached_data
    print("[DEBUG] 请求获取 blrec 类型的所有数据")
    cached_data = fetch_data()
    blrec_data = [d for d in cached_data if d["rectpye"] == "blrec"]
    print(f"[DEBUG] 获取到的 blrec 数据数量: {len(blrec_data)}")
    return {"data": blrec_data}


# 获取 recheme 指定数据
@app.get("/api/data/recheme/{roomId:int}")
async def get_recheme_room_by_id(roomId: int):
    print('[DEBUG] 调用路径 @app.get("/api/data/recheme/{roomId:int}")')
    print(f"[DEBUG] 请求获取 recheme 类型房间ID为 {roomId} 的数据")
    recheme_room_data = fetch_room_data(str(roomId), "recheme")
    if not recheme_room_data:
        print("[ERROR] 录播姬中不存在该直播间")
        raise HTTPException(status_code=404, detail="录播姬中不存在该直播间")
    return {"data": recheme_room_data}


# 获取 blrec 指定数据
@app.get("/api/data/blrec/{roomId:int}")
async def get_blrec_room_by_id(roomId: int):
    print('[DEBUG] 调用路径 @app.get("/api/data/blrec/{roomId:int}")')
    print(f"[DEBUG] 请求获取 blrec 类型房间ID为 {roomId} 的数据")
    blrec_room_data = fetch_room_data(str(roomId), "blrec")
    if not blrec_room_data:
        print("[ERROR] BLREC中不存在该直播间")
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
