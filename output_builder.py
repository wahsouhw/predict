"""
    输出构建模块
"""
import json
from datetime import datetime
from typing import Dict


def _build_common(request_info: Dict) -> Dict:
    """公共外壳"""
    start = request_info.get("call_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "status": 200,
        "message": "操作成功",
        "bussnessNo": request_info.get("business_no", ""),
        "assessmentTime": request_info.get("assessment_time", ""),
        "dataTime": f"{start}~{end}",
        "deviceId": request_info.get("device_id", ""),
    }


def _build_material_datas(predictions, battery_result, slip_ring_result):
    """构建三元件 materialDatas"""
    material_datas = []
    unit_map = {"IMU模块": "个", "电池": "个", "滑环": "圈"}

    for comp_name in ["电池", "IMU模块", "滑环"]:
        if comp_name in predictions:
            info = predictions[comp_name]
            if comp_name == "电池" and battery_result:
                info = battery_result
            if comp_name == "滑环" and slip_ring_result:
                info = slip_ring_result
            material_datas.append({
                "materialName": comp_name,
                "needNum": str(info["need"]),
                "materialUnit": unit_map.get(comp_name, "个")
            })
    return material_datas


def _build_sysysm(predictions, battery_result, slip_ring_result):
    """构建 SYSYSM 列表"""
    sysysm_list = []
    for comp_name in ["电池", "IMU模块", "滑环"]:
        if comp_name == "滑环":
            if slip_ring_result:
                sysysm_list.append(slip_ring_result["rul"])
            elif comp_name in predictions:
                sysysm_list.append(predictions[comp_name]["rul"])
            else:
                sysysm_list.append("未知")
        else:
            if comp_name == "电池" and battery_result:
                rul_str = battery_result["rul"]
            elif comp_name in predictions:
                rul_str = predictions[comp_name]["rul"]
            else:
                sysysm_list.append("未知")
                continue
            try:
                rul_days = int(rul_str.replace("天", ""))
                sysysm_list.append(f"{round(rul_days / 365, 2)}年")
            except Exception:
                sysysm_list.append(rul_str)
    return sysysm_list


def _build_avg_confidence(predictions, battery_result, slip_ring_result):
    """计算平均置信度"""
    from model import calculate_average_confidence
    confidences = {}
    for comp_name in ["电池", "IMU模块", "滑环"]:
        if comp_name == "电池" and battery_result:
            confidences[comp_name] = battery_result
        elif comp_name == "滑环" and slip_ring_result:
            confidences[comp_name] = slip_ring_result
        elif comp_name in predictions:
            confidences[comp_name] = predictions[comp_name]
    return calculate_average_confidence(confidences)


def build_output(request_info: Dict, predictions: Dict, extra_data: Dict,
                 battery_result: Dict = None, slip_ring_result: Dict = None,
                 faults: list = None) -> Dict:
    """
    status=2：三元件寿命预测

    faults: 故障原因列表（来自健康管理的 GZYY）
        - 有几个故障就输出几段
        - 每段 fault 不同，materialDatas 相同
        - 全无故障时 faults = [""]
    """
    if faults is None:
        faults = ["xxx"]

    # materialDatas
    material_datas = _build_material_datas(predictions, battery_result, slip_ring_result)

    # SYSYSM
    sysysm_list = _build_sysysm(predictions, battery_result, slip_ring_result)

    # 置信度
    avg_conf = _build_avg_confidence(predictions, battery_result, slip_ring_result)

    # 每个 fault 一段
    material_prediction_datas = [
        {
            "fault": f,
            "materialDatas": material_datas
        }
        for f in faults
    ]

    result = _build_common(request_info)
    result["materialPrediction"] = {
        "materialPredictionDatas": material_prediction_datas,
        "extraData": {
            "YCBJ": str(["UPS电源", "IMU模块", "滑环"]),
            "YCSC": extra_data.get("YCSC", "[3年, 20年, 10000000圈]"),
            "SYSYSM": str(sysysm_list),
            "YCXQZXD": f"{avg_conf:.2f}"
        }
    }
    return result


def build_repair_output(request_info: Dict, repair_items: list) -> Dict:
    """status=3：维修性列表"""
    result = _build_common(request_info)
    result["materialPrediction"] = {
        "materialPredictionDatas": repair_items
    }
    return result


def send_callback(callback_url: str, result_data: Dict) -> bool:
    if not callback_url:
        return True
    try:
        import requests
        response = requests.post(callback_url, json=result_data, timeout=10)
        return response.status_code == 200
    except Exception:
        return False