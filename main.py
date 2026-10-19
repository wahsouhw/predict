"""
    器材寿命预测服务

    status：
        1 = 三元件寿命预测
        2 = 预防性工单
        3 = 维修性列表
"""
import json
import threading
from datetime import datetime
from typing import Optional, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from config import *
import input_parser as inp
import model as mdl
from output_builder import build_output, build_repair_output, send_callback

app_internal = FastAPI(title="器材寿命预测-内部")
app_external = FastAPI(title="器材寿命预测-外部")


# 调用结果打印到output.txt中（每次覆盖）
def log_to_file(tag: str, data):
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {tag}\n")
            f.write("=" * 60 + "\n")
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
            f.write("\n")
    except Exception:
        pass


# 全局状态
# 请求计数器（MQTT 每条消息 +1，到阈值触发预测）
request_counter = 0
# 上次预测时间
last_predict_time = None
# 上次预测结果缓存
cached_result = None

latest_point_datas = {}    # MQTT 最新
latest_health = {}         # 健康管理最新
latest_device_info = {}    # MQTT 里的设备信息



def make_rated_result():
    """
    未预测时返回的额定值
    """
    predictions = {
        "IMU模块": {"rul": "7300天", "need": 0, "confidence": 1.0},
        "电池": {"rul": "1095天", "need": 0, "confidence": 1.0},
        "滑环": {"rul": "10000000圈", "need": 0, "confidence": 1.0},
    }
    return build_output(
        request_info={
            "board_no": latest_device_info.get("boardNo", ""),
            "device_id": latest_device_info.get("deviceId", ""),
            "business_no": latest_device_info.get("businessNo", ""),
            "assessment_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "call_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        predictions=predictions,
        extra_data={"YCSC": "[3年,20年,10000000圈]"},
        battery_result={"rul": "1095天", "need": 0, "confidence": 1.0},
        slip_ring_result={"rul": "10000000圈", "need": 0, "confidence": 1.0},
        faults=[""],
    )

def get_last_need(cached, component_name):
    """从上次缓存里取元件的 needNum"""
    if not cached or not isinstance(cached, dict):
        return 0

    try:
        datas = cached.get("materialPrediction", {}).get("materialPredictionDatas", [])
        if not datas or not isinstance(datas, list):
            return 0
        material_datas = datas[0].get("materialDatas", [])
        for item in material_datas:
            if item.get("materialName") == component_name:
                return int(item.get("needNum", 0))
    except Exception:
        pass
    return 0

class PredictRequest(BaseModel):
    """外部调用请求参数"""
    boardNo: str
    deviceName: str
    deviceId: str
    deviceType: Optional[str] = ""
    businessNo: str
    status: Optional[str] = "1"
    assessmentTime: Optional[str] = None
    callback: str
    pointDatas: Optional[Dict] = {}
    extraData: Optional[Dict] = {}


# 触发判断
def should_predict() -> bool:
    """
    首次或计数器到阈值时触发预测
    """
    global request_counter, last_predict_time
    if last_predict_time is None:
        return True
    return request_counter >= PREDICT_COUNTER_THRESHOLD


# 完整预测
def do_full_predict():
    global cached_result, last_predict_time, request_counter

    # 健康管理没到 → 跳过
    if not latest_health:
        print("[main] 健康管理数据还没到，跳过")
        return None

    # ===== 解析健康管理数据 =====
    health = inp.extract_health_data(latest_health)
    sensors = health["sensors"]

    # ===== 检查结构 + 12传感器是否齐全 =====
    # 结构错：healthManage/extraData 缺失
    h_extra = latest_health.get("healthManage", {}).get("extraData", {})
    if not h_extra:
        print("[main] 健康管理数据结构错误，跳过")
        return None

    # 12传感器缺失
    missing = [name for name in ALL_SENSOR_NAMES if sensors.get(name) is None]
    if missing:
        print(f"[main] 健康管理缺少传感器: {missing}，跳过")
        return None

    call_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ===== 1. 解析健康管理数据 =====
    health = inp.extract_health_data(latest_health)
    sensors = health["sensors"]

    # ===== 2. 设备信息 =====
    device_id = latest_device_info.get("deviceId", "1")
    business_no = latest_device_info.get("businessNo", "")
    board_no = latest_device_info.get("boardNo", "001")
    assessment_time = latest_health.get("assessmentTime") or call_time

    # ===== 3. 取故障现象（GZZT 索引 → 故障现象） =====
    h_extra = latest_health.get("healthManage", {}).get("extraData", {})
    gzzt_list = inp.parse_fault_list(h_extra.get("GZZT", ""))

    faults = []
    for i, v in enumerate(gzzt_list):
        if v and v != "无故障":
            faults.append(FAULT_NAME_MAP.get(i, v))
    if not faults:
        faults = [""]

    # ===== 4. 查历史数据 =====
    historical_data = inp.query_all_history()

    # ===== 5. 拿电压 =====
    offline = inp.fetch_offline_data() or {}
    voltage = offline.get("upsVoltage")
    voltage_valid = "1" if voltage is not None else "0"

    # IMU 换件
    # IMU 换件（上次 need=1 且离线已用 < 阈值）
    imu_used = offline.get("imu模块")
    if get_last_need(cached_result, "IMU模块") == 1 and imu_used is not None and imu_used < REPLACE_THRESHOLD_YEARS:
        print(f"[main] IMU 已换件（已用 {imu_used} 年），重置")
        mdl.reset_component_start_time("IMU模块")

    # 电池换件
    ups_used = offline.get("ups电源")
    if get_last_need(cached_result, "电池") == 1 and ups_used is not None and ups_used < REPLACE_THRESHOLD_YEARS:
        print(f"[main] 电池 已换件（已用 {ups_used} 年），重置")
        mdl.reset_component_start_time("电池")

    # 滑环换件
    ring_used = offline.get("滑环")
    if get_last_need(cached_result, "滑环") == 1 and ring_used is not None and ring_used < REPLACE_THRESHOLD_ROTATIONS:
        print(f"[main] 滑环 已换件（已用 {ring_used} 圈），重置")
        mdl.reset_slip_ring()

    # ===== 6. 已用时间（时间差） =====
    imu_days = mdl.get_component_used_days("IMU模块")
    ups_days = mdl.get_component_used_days("电池")

    # ===== 7. 三元件预测 =====
    imu_result = mdl.predict_imu_life(historical_data, sensors, imu_days)
    battery_result = mdl.predict_battery_life(ups_days, voltage, voltage_valid)
    slip_ring_result = mdl.predict_slip_ring_life()

    predictions = {
        "IMU模块": imu_result,
        "电池": battery_result,
        "滑环": slip_ring_result,
    }

    # # ===== 8. need=1 重置 =====
    # if imu_result["need"] == 1:
    #     mdl.reset_component_start_time("IMU模块")
    # if battery_result["need"] == 1:
    #     mdl.reset_component_start_time("电池")
    # if slip_ring_result["need"] == 1:
    #     mdl.reset_slip_ring()

    # ===== 9. 组装输出 =====
    extra_data = {"YCSC": "[3年,20年,10000000圈]"}
    final_result = build_output(
        request_info={
            "board_no": board_no,
            "device_id": device_id,
            "business_no": business_no,
            "assessment_time": assessment_time,
            "call_time": call_time,
        },
        predictions=predictions,
        extra_data=extra_data,
        battery_result=battery_result,
        slip_ring_result=slip_ring_result,
        faults=faults,
    )

    cached_result = final_result
    last_predict_time = datetime.now()
    request_counter = 0

    send_callback(DEFAULT_CALLBACK_URL, final_result)
    return final_result



# 内部 app（接收健康管理广播）
@app_internal.get("/health")
async def health_check():
    return {
        "status": "ok",
        "request_counter": request_counter,
        "slip_ring_total": f"{mdl.get_slip_ring_total()}圈",
        "has_cached": bool(cached_result),
        "has_health": bool(latest_health),
    }


# @app_internal.post("/from_health")
# async def from_health(request: Request):
#     global latest_health
#     latest_health = await request.json()
#
#     return {"status": 200, "message": "ok"}

@app_internal.post("/from_health")
async def from_health(request: Request):
    global latest_health
    latest_health = await request.json()

    # 只打 12 个传感器值
    h_extra = latest_health.get("healthManage", {}).get("extraData", {})

    def gv(k):
        """从 extraData 里取值（可能是 dict 或直接值）"""
        v = h_extra.get(k)
        if isinstance(v, dict):
            return v.get("value")
        return v

    # print(f"[③ from_health] "
    #       f"经纬度  = {gv('GXZZDHSJJD')} / {gv('GXZZDHSJWD')} | "
    #       f"陀螺零偏 X/Y/Z = {gv('YCLBXZTLLP')} / {gv('YCLBYZTLLP')} / {gv('YCLBZZTLLP')} | "
    #       f"加表零偏 X/Y/Z = {gv('YCLBXZJBLP')} / {gv('YCLBYZJBLP')} / {gv('YCLBZZJBLP')} | "
    #       f"抖频 X/Y/Z = {gv('GXZZDPX')} / {gv('GXZZDPY')} / {gv('GXZZDPZ')} | "
    #       f"和频 X/Y/Z = {gv('GXZZHPX')} / {gv('GXZZHPY')} / {gv('GXZZHPZ')}")

    return {"status": 200, "message": "ok"}

# 外部 app
@app_external.post(PREDICT_PATH)
async def predict(request: PredictRequest):
    global latest_device_info

    try:
        request_data = request.model_dump()
        status = str(request_data.get("status", "1"))
        call_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 更新设备信息（外部调用的 deviceId 等）
        for k in ["boardNo", "deviceId", "deviceType", "businessNo"]:
            if request_data.get(k):
                latest_device_info[k] = request_data[k]

        if status == "2":
            # 预测
            print("[main] status=2，跑完整预测")
            result = do_full_predict()
            if result:
                log_to_file("status=2 预测结果", result)
                return result
            return cached_result or {}

        elif status == "1":
            print("[main] status=1，预防性工单")
            h_extra = latest_health.get("healthManage", {}).get("extraData", {})
            gzzt_list = inp.parse_fault_list(h_extra.get("GZZT", ""))
            faults = []
            for i, v in enumerate(gzzt_list):
                if v and v != "无故障":
                    faults.append(FAULT_NAME_MAP.get(i, v))
            if not faults:
                faults = [""]
            default_materials = [
                {"materialName": "导电橡胶绳", "needNum": "1", "materialUnit": "个"},
                {"materialName": "惯性装置风扇", "needNum": "1", "materialUnit": "个"},
                {"materialName": "显控发送装置风扇", "needNum": "1", "materialUnit": "个"},
                {"materialName": "开关按键", "needNum": "1", "materialUnit": "个"},
            ]

            repair_items = [
                {"fault": f, "materialDatas": default_materials}
                for f in faults
            ]

            result = build_repair_output(
                request_info={
                    "board_no": request_data.get("boardNo", ""),
                    "device_id": request_data.get("deviceId", ""),
                    "business_no": request_data.get("businessNo", ""),
                    "assessment_time": request_data.get("assessmentTime", ""),
                    "call_time": call_time,
                },
                repair_items=repair_items,
            )
            log_to_file("status=1 预防工单", result)
            return result

        elif status == "3":
            # 维修清单
            print("[main] status=3，生成维修清单")
            health = inp.extract_health_data(latest_health)
            gzzt = inp.parse_fault_list(health.get("GZZT"))
            gzyy = inp.parse_fault_list(health.get("GZYY"))
            repair_items = mdl.do_repair_list(gzzt, gzyy)
            result = build_repair_output(
                request_info={
                    "board_no": request_data.get("boardNo", ""),
                    "device_id": request_data.get("deviceId", ""),
                    "business_no": request_data.get("businessNo", ""),
                    "assessment_time": request_data.get("assessmentTime", ""),
                    "call_time": call_time,
                },
                repair_items=repair_items,
            )
            log_to_file("status=3 维修清单", result)
            return result

        else:
            return cached_result or {}

    except Exception as e:
        log_to_file("预测异常", {"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))



# MQTT
def on_mqtt_message(client, userdata, msg):
    global latest_point_datas, latest_device_info, request_counter

    try:
        raw = json.loads(msg.payload.decode("utf-8"))
        latest_point_datas = inp.parse_mqtt_message(raw)

        # angle = latest_point_datas.get("GXZZYSSJZTJ1")
        # print(f"[MQTT] 测角={angle}")

        for k in ["boardNo", "deviceId", "deviceType", "businessNo"]:
            if k in raw:
                latest_device_info[k] = raw[k]

        # 更新滑环
        angle = inp.extract_slip_ring_angle(latest_point_datas)
        mdl.update_slip_ring_rotations(angle)

        request_counter += 1

        if should_predict():
            print(f"[main] 触发预测，计数器={request_counter}")
            do_full_predict()
        else:
            if cached_result:
                send_callback(DEFAULT_CALLBACK_URL, cached_result)
            else:
                rated = make_rated_result()
                send_callback(DEFAULT_CALLBACK_URL, rated)

    except Exception as e:
        print(f"[main-MQTT] 处理失败: {e}")


def on_mqtt_connect(client, userdata, flags, rc):
    print(f"[main-MQTT] 已连接 rc={rc}, 订阅 {MQTT_TOPIC}")
    client.subscribe(MQTT_TOPIC)


def start_mqtt_thread():
    import paho.mqtt.client as mqtt
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    client.on_connect = on_mqtt_connect
    client.on_message = on_mqtt_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    print(f"[main-MQTT] 连接 {MQTT_BROKER}:{MQTT_PORT}")
    client.loop_forever()



# 启动
def run_internal():
    # uvicorn.run(app_internal, host=INTERNAL_HOST, port=INTERNAL_PORT, log_level="info")
    uvicorn.run(app_internal, host=INTERNAL_HOST, port=INTERNAL_PORT,
                log_level="warning", access_log=False)

def run_external():
    # uvicorn.run(app_external, host=EXTERNAL_HOST, port=EXTERNAL_PORT, log_level="info")
    uvicorn.run(app_external, host=EXTERNAL_HOST, port=EXTERNAL_PORT,
                log_level="warning", access_log=False)


if __name__ == "__main__":
    print("=" * 60)
    print("器材寿命预测服务启动")
    print("=" * 60)
    print(f"内部端口: http://{INTERNAL_HOST}:{INTERNAL_PORT}")
    print(f"外部端口: http://{EXTERNAL_HOST}:{EXTERNAL_PORT}")
    print(f"MQTT: {MQTT_BROKER}:{MQTT_PORT}, 订阅 {MQTT_TOPIC}")
    print(f"触发阈值: {PREDICT_COUNTER_THRESHOLD} 次")
    print("=" * 60)

    mdl.init_component_start_time()

    threading.Thread(target=start_mqtt_thread, daemon=True).start()
    threading.Thread(target=run_internal, daemon=True).start()
    run_external()