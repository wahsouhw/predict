"""
    输入解析模块 - 所有数据获取
    包含：MQTT解析、健康管理解析、历史数据获取、离线接口
"""
import requests
from typing import Dict, List
from config import (
    SQL_API_URL, OFFLINE_API_URL,
    ALL_SENSOR_NAMES, SLIP_RING_ANGLE_FIELD,
)


# MQTT 解析
def parse_mqtt_message(raw: dict) -> dict:
    """
    从 MQTT的 sj 中 提取 pointDatas

    输入: {"crt": ..., "sj": [{测点数据}], "sjn": ...}
    返回: {"GXZZYSSJZTJ1": "90.000", ...}
    """
    sj = raw.get("sj", [])
    if sj and isinstance(sj, list):
        return sj[0]
    return raw.get("pointDatas", raw)


def extract_slip_ring_angle(point_datas: dict):
    """
    从 pointDatas 提取测角值
    """
    if not point_datas:
        return None
    # 获取测角值
    v = point_datas.get(SLIP_RING_ANGLE_FIELD)
    if v is None:
        return None
    if isinstance(v, dict):
        vals = v.get("value", [])
        if isinstance(vals, list) and vals:
            return float(vals[-1])
        if vals is not None:
            return float(vals)
        return None
    return float(v)


# 健康管理数据解析
def extract_health_data(health_data: dict) -> dict:
    """
    从健康管理输出提取：
        - 12个传感器当前值
        - GXZZWD 温度
        - GZZT / GZYY

    输入: {"healthManage": {"extraData": {...}}}
    """
    h_extra = health_data.get("healthManage", {}).get("extraData", {})

    result = {"sensors": {}, "GZZT": None, "GZYY": None}

    # 12个传感器 + 温度
    for name in ALL_SENSOR_NAMES + ["GXZZWD"]:
        v = h_extra.get(name)
        if v is None:
            result["sensors"][name] = None
            continue

        if isinstance(v, dict):
            val = v.get("value")
            if isinstance(val, list) and val:
                result["sensors"][name] = float(val[-1])
            elif val is not None:
                result["sensors"][name] = float(val)
            else:
                result["sensors"][name] = None
        else:
            try:
                result["sensors"][name] = float(v)
            except (ValueError, TypeError):
                result["sensors"][name] = None

    # GZZT / GZYY
    result["GZZT"] = h_extra.get("GZZT")
    result["GZYY"] = h_extra.get("GZYY")

    return result


def parse_fault_list(s) -> list:
    """
    把形如 "[无故障, 无故障, 航姿跳变, ...]" 的字符串，解析成 Python 列表

    '[无故障, 无故障, ...]' -> ['无故障', '无故障', ...]
    """
    if not s:
        return []
    if isinstance(s, list):
        return s
    if isinstance(s, str):
        s = s.strip()
        if s.startswith("[") and s.endswith("]"):
            content = s[1:-1]
            return [x.strip() for x in content.split(",")]
    return []


# 历史数据获取（接口，5000条快照）
def query_all_history() -> Dict[str, List[float]]:
    # 初始化空结果
    empty = {name: [] for name in ALL_SENSOR_NAMES}

    # 发请求
    try:
        r = requests.get(SQL_API_URL, timeout=30)
        data = r.json()

    # 检查数据
    except Exception as e:
        print(f"[input] 查历史失败: {e}")
        return empty

    if not data:
        print("[input] 查历史失败: 返回空")
        return empty

    value = data.get("value")
    if not value:
        print("[input] 查历史失败: value 为空")
        return empty

    records = value.get("data", []) if isinstance(value, dict) else []
    if not records:
        print("[input] 查历史失败: data 为空")
        return empty

    print(f"[input] 数据接口拿到 {len(records)} 条数据")

    result = {name: [] for name in ALL_SENSOR_NAMES}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for name in ALL_SENSOR_NAMES:
            v = rec.get(name)
            if isinstance(v, dict):
                val = v.get("value")
                if isinstance(val, list) and val:
                    result[name].append(float(val[-1]))
                elif val is not None:
                    result[name].append(float(val))
            elif v is not None:
                try:
                    result[name].append(float(v))
                except (ValueError, TypeError):
                    pass

    # 打印每个传感器多少条
    print(f"[input] 各传感器历史条数: {[(k, len(v)) for k, v in result.items()]}")

    for name in result:
        result[name] = list(reversed(result[name]))

    return result



# 离线接口
def _parse_years(val):
    """
    把离线接口返回的“带单位字符串”转成纯数字

    '2.4年' -> 2.4；'9600000圈' -> 9600000.0
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.replace("年", "").replace("圈", "").strip())
        except Exception:
            return None
    return None


def fetch_offline_data():
    """
    调离线接口，拿电压 + 三元件已用寿命（任意组合）

    返回：
        {
            "upsVoltage": 24 或 None,
            "ups电源": 2.4 或 None,      # 年
            "imu模块": 0.5 或 None,      # 年
            "滑环": 9600000 或 None,     # 圈
        }
    """
    try:
        r = requests.get(OFFLINE_API_URL, timeout=5)
        data = r.json()
        if not data:
            print("[离线接口] 返回空")
            return None
        v = data.get("value")
        if not v:
            print("[离线接口] value 为空")
            return None

        result = {
            "upsVoltage": v.get("upsVoltage"),
            "ups电源": _parse_years(v.get("ups电源")),
            "imu模块": _parse_years(v.get("imu模块")),
            "滑环": _parse_years(v.get("滑环")),
        }

        # print(f"[离线接口] {result}")

        return result
    except Exception as e:
        print(f"[input] 离线接口失败: {e}")
        return None
