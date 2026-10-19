"""
    预测模型 - IMU / 电池 / 滑环 + 维修性列表

    时间差方案：IMU 和电池用 (当前时间 - 开始时间)
    滑环：累计圈数
"""
import math
import time
import numpy as np
import torch
from typing import Dict, List, Optional, Tuple

from config import (
    FIXED_LIFE, WARNING_THRESHOLD,
    PREDICTION_LENGTH, MIN_HISTORY_LENGTH,
    GYRO_MEAN_THRESHOLD, GYRO_VAR_THRESHOLD,
    ACC_MEAN_THRESHOLD, ACC_VAR_THRESHOLD,
    SLIP_RING_TOTAL_LIFE, SLIP_RING_SHUTDOWN_THRESHOLD,
    SLIP_RING_HALF_TURN_DEGREE, SLIP_RING_THRESHOLD_RATIO,
    BATTERY_DESIGN_LIFE, BATTERY_VOLTAGE_THRESHOLD,
    BATTERY_WARNING_DAYS,
    FAULT_MAP, HANGZI_FAULT, HANGZI_MATERIALS,
)
from chronos_local import ChronosPipeline

_pipeline = None


# ============================================================
# 部件开始时间（时间差方案）
# ============================================================
component_start_time = {
    "电池": None,
    "IMU模块": None,
}


def init_component_start_time():
    """服务启动时初始化"""
    now = time.time()
    for comp in component_start_time:
        component_start_time[comp] = now
    print(f"[model] 部件开始时间已初始化")


def get_component_used_days(component: str) -> float:
    """用当前时间 - 开始时间 算已用天数"""
    start = component_start_time.get(component)
    if start is None:
        return 0.0
    return (time.time() - start) / 86400


def reset_component_start_time(component: str):
    """重置指定部件的开始时间"""
    component_start_time[component] = time.time()
    print(f"[model] {component} 已重置开始时间")


# ============================================================
# RAF 模型
# ============================================================
def get_raf_pipeline():
    global _pipeline
    if _pipeline is None:
        try:
            _pipeline = ChronosPipeline.from_pretrained(
                "./chronos-t5-base",
                device_map="cuda:0" if torch.cuda.is_available() else "cpu",
                torch_dtype=torch.bfloat16
            )
            print("[model] RAF 模型加载成功")
        except Exception as e:
            print(f"[model] RAF 加载失败: {e}")
            _pipeline = None
    return _pipeline


def predict_sequence_with_raf(data: List[float]) -> Optional[List[float]]:
    if len(data) < 30:
        return None
    pipeline = get_raf_pipeline()
    if pipeline is None:
        return predict_sequence_linear(data)

    try:
        context = data[-5000:] if len(data) > 5000 else data
        mean = np.mean(context)
        std = np.std(context) + 1e-7
        context_norm = (context - mean) / std

        with torch.no_grad():
            tensor = torch.tensor(context_norm, dtype=torch.float32).unsqueeze(0)
            predictions = pipeline.predict(tensor, prediction_length=PREDICTION_LENGTH, num_samples=20)

        predictions_denorm = predictions * std + mean
        pred_median = predictions_denorm.median(dim=1).values.cpu().numpy()[0]
        return pred_median.tolist()
    except Exception as e:
        print(f"[model] RAF 预测失败: {e}")
        return predict_sequence_linear(data)


def predict_sequence_linear(data: List[float]) -> Optional[List[float]]:
    if len(data) < 5:
        return None
    x = np.arange(len(data))
    slope, intercept = np.polyfit(x, data, 1)
    future_x = np.arange(len(data), len(data) + PREDICTION_LENGTH)
    return (slope * future_x + intercept).tolist()


# ============================================================
# IMU 健康评估
# ============================================================
def check_prediction_stats(predicted_seq, sensor_name):
    """检查64条预测值的均值/方差是否超标"""
    if not predicted_seq or len(predicted_seq) < 2:
        return False

    # 抖频、和频不判阈值
    if "DP" in sensor_name or "HP" in sensor_name:
        return False

    if "ZTLLP" in sensor_name:
        sensor_type = "gyro"
    elif "ZJBLP" in sensor_name:
        sensor_type = "acc"
    else:
        return False

    arr = np.array(predicted_seq)
    mean_val = np.mean(arr)
    var_val = np.var(arr)

    if sensor_type == "gyro":
        return abs(mean_val) >= GYRO_MEAN_THRESHOLD or var_val >= GYRO_VAR_THRESHOLD
    else:
        return abs(mean_val) >= ACC_MEAN_THRESHOLD or var_val >= ACC_VAR_THRESHOLD


def calculate_health_factor(historical_data, current_value, sensor_name=""):
    if len(historical_data) < 5 or current_value is None:
        return 0.5, None

    predicted_seq = predict_sequence_with_raf(historical_data)
    if predicted_seq is None or len(predicted_seq) == 0:
        return 0.5, None

    if check_prediction_stats(predicted_seq, sensor_name):
        return 0.0, predicted_seq[1:]

    predicted_first = predicted_seq[0]
    error = abs(predicted_first - current_value)
    std_dev = np.std(historical_data)

    if std_dev < 1e-10:
        health = max(0.3, 1 - error / 0.001)
    else:
        health = max(0.3, 1 - error / (3 * std_dev))

    return float(health), predicted_seq[1:]


def calculate_imu_health_score(historical_data, current_values):
    print("\n" + "=" * 60)
    print("各传感器健康评估")
    print("=" * 60)

    from config import IMU_SENSOR_NAMES, DP_SENSOR_NAMES, HP_SENSOR_NAMES

    def eval_group(sensor_names, group_name):
        factors = []
        for name in sensor_names:
            history = historical_data.get(name, [])
            current = current_values.get(name)
            if len(history) < 5 or current is None:
                print(f"   [{group_name}] {name}: 数据不足，跳过")
                continue
            health, _ = calculate_health_factor(history, current, name)
            factors.append(health)
            print(f"   [{group_name}] {name}: {health:.3f}")
        return factors

    lb = eval_group(IMU_SENSOR_NAMES, "零偏")
    dp = eval_group(DP_SENSOR_NAMES, "抖频")
    hp = eval_group(HP_SENSOR_NAMES, "和频")

    lb_avg = np.mean(lb) if lb else 0.5
    dp_avg = np.mean(dp) if dp else 0.5
    hp_avg = np.mean(hp) if hp else 0.5
    total = 0.6 * lb_avg + 0.2 * dp_avg + 0.2 * hp_avg

    print(f"\n综合健康分数: {total:.3f}")
    return float(total)


def predict_imu_life(historical_data, current_values, used_days):
    """IMU 预测"""
    from config import COMPONENT_MAP

    if not historical_data:
        return {"rul": "7300天", "need": 0, "confidence": 1.0}

    # 历史数据不足
    data_enough = all(
        len(values) >= MIN_HISTORY_LENGTH
        for values in historical_data.values()
    )
    if not data_enough:
        return {"rul": "7300天", "need": 0, "confidence": 1.0}

    health_score = calculate_imu_health_score(historical_data, current_values)

    design_life = FIXED_LIFE["IMU模块"]
    if health_score <= 0:
        return {"rul": "0天", "need": 1, "confidence": 1.0}

    base_rul = max(0, design_life - used_days)
    rul = base_rul * health_score
    confidence = max(0.80, 0.95 - (1 - health_score) * 0.3)
    confidence = round(min(confidence, 0.95), 4)

    need = 1 if rul < design_life * WARNING_THRESHOLD else 0

    return {"rul": f"{int(rul)}天", "need": need, "confidence": confidence}


# ============================================================
# 电池预测
# ============================================================
def predict_battery_life(used_days, voltage=None, voltage_valid="1"):
    if voltage_valid != "1" or voltage is None:
        # 电压无效 → 不报警，按正常衰减算
        pass
    elif voltage < BATTERY_VOLTAGE_THRESHOLD:
        return {"rul": "0天", "need": 1, "confidence": 1.0}

    base_remaining = BATTERY_DESIGN_LIFE - used_days
    ratio = used_days / BATTERY_DESIGN_LIFE
    health = 1 - 0.2 * ratio * ratio
    remaining = max(0, base_remaining * health)
    need = 1 if remaining < BATTERY_WARNING_DAYS else 0

    return {"rul": f"{int(remaining)}天", "need": need, "confidence": 0.95}


# ============================================================
# 滑环
# ============================================================
slip_ring_total_rotations = 0.0
slip_ring_prev_angle = None
slip_ring_accumulated = 0.0


def count_rotations(prev_angle, curr_angle, accumulated):
    delta = abs(curr_angle - prev_angle)
    if delta < SLIP_RING_SHUTDOWN_THRESHOLD:
        return 0.0, accumulated
    accumulated += delta
    half_turns = accumulated // SLIP_RING_HALF_TURN_DEGREE
    new_accumulated = accumulated % SLIP_RING_HALF_TURN_DEGREE
    return half_turns * 0.5, new_accumulated


def get_slip_ring_total() -> float:
    """获取滑环累计圈数"""
    return slip_ring_total_rotations


def update_slip_ring_rotations(curr_angle):
    global slip_ring_total_rotations, slip_ring_prev_angle, slip_ring_accumulated

    if curr_angle is None:
        return
    if slip_ring_prev_angle is None:
        slip_ring_prev_angle = curr_angle
        return

    rotations, slip_ring_accumulated = count_rotations(
        slip_ring_prev_angle, curr_angle, slip_ring_accumulated
    )
    slip_ring_total_rotations += rotations
    slip_ring_prev_angle = curr_angle


def reset_slip_ring():
    global slip_ring_total_rotations, slip_ring_prev_angle, slip_ring_accumulated
    slip_ring_total_rotations = 0.0
    slip_ring_prev_angle = None
    slip_ring_accumulated = 0.0
    print("[model] 滑环累计圈数已归零")


def predict_slip_ring_life():
    """滑环预测（用累计圈数）"""
    remaining = SLIP_RING_TOTAL_LIFE * math.exp(-slip_ring_total_rotations / SLIP_RING_TOTAL_LIFE)

    if slip_ring_total_rotations / SLIP_RING_TOTAL_LIFE >= (1 - SLIP_RING_THRESHOLD_RATIO):
        need = 1
    else:
        need = 0

    return {"rul": f"{int(remaining)}圈", "need": need, "confidence": 0.95}


# ============================================================
# 维修性列表（status=3）
# ============================================================
def do_repair_list(gzzt: list, gzyy: list) -> list:
    """
    根据 GZZT / GZYY 生成维修清单

    fault: GZZT[i] 的值（故障现象）
    materialDatas: 用 GZYY[i] 查 FAULT_MAP
    """
    results = []

    for i in range(6):
        gzzt_val = gzzt[i] if i < len(gzzt) else "无故障"
        if gzzt_val == "无故障":
            continue

        # fault 用 GZZT
        fault = gzzt_val

        if i == 2:
            # 航姿跳变，固定清单
            materials = HANGZI_MATERIALS
        else:
            # 其他：用 GZYY 查表
            gzyy_val = gzyy[i] if i < len(gzyy) else ""
            materials = FAULT_MAP.get((i, gzyy_val), [])

        material_datas = [
            {"materialName": name, "needNum": "1", "materialUnit": "个"}
            for name in materials
        ]

        results.append({
            "fault": fault,
            "materialDatas": material_datas
        })

    return results


# ============================================================
# 预防性工单（status=2，空）
# ============================================================
def do_prevent_work_order():
    """暂未实现"""
    return None


# ============================================================
# 置信度
# ============================================================
def calculate_average_confidence(results: Dict) -> float:
    confidences = [info["confidence"] for info in results.values()]
    return sum(confidences) / len(confidences) if confidences else 0.95
