# 服务配置
# 内部监听
INTERNAL_HOST = "0.0.0.0"
INTERNAL_PORT = 8090
# 外部监听
EXTERNAL_HOST = "0.0.0.0"
EXTERNAL_PORT = 8091
# 外部调用
PREDICT_PATH = "/equipForecast/point/data/interialEquip"
# 维修决策获取器材需求预测数据接口
DEFAULT_CALLBACK_URL = "http://127.0.0.1:8092/from_model1"

# 数据（库）接口，取历史5000条消息
# SQL_API_URL = "http://127.0.0.1:7376/health/model/getStatusEvaluates"
SQL_API_URL = "http://192.168.2.202:7373/health/epPatrolDetailPlan/getManage/0512000010001"

# 离线接口，取电压，三个器件的使用时间
OFFLINE_API_URL = "http://192.168.2.203:7373/health/offline/data?equipNo=0512000010001&boardNo=100"
# OFFLINE_API_URL = "http://127.0.0.1:7373/health/offline/data?equipNo=0512000010001&boardNo=100"


# 日志名称
LOG_FILE = "output.txt"


# MQTT
# MQTT_BROKER = "192.168.2.202"
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
# MQTT_BROKER = "broker.emqx.io"
MQTT_TOPIC = "GDXT/0512000010001/1"


# 传感器
# 零偏
IMU_SENSOR_NAMES = [
    "YCLBXZTLLP", "YCLBYZTLLP", "YCLBZZTLLP",
    "YCLBXZJBLP", "YCLBYZJBLP", "YCLBZZJBLP"
]
# 抖频
DP_SENSOR_NAMES = ["GXZZDPX", "GXZZDPY", "GXZZDPZ"]
# 和频
HP_SENSOR_NAMES = ["GXZZHPX", "GXZZHPY", "GXZZHPZ"]
# 全部传感器
ALL_SENSOR_NAMES = IMU_SENSOR_NAMES + DP_SENSOR_NAMES + HP_SENSOR_NAMES


# 部件
COMPONENT_MAP = {
    "UPS电源": "电池",              # ？？？
    "IMU模块": "IMU模块",
    "滑环": "滑环"
}
# 额定寿命
FIXED_LIFE = {
    "UPS电源": 1095,
    "IMU模块": 7300,
    "滑环": 10000000
}
# 寿命阈值
WARNING_THRESHOLD = 0.1


# IMU
# 触发阈值，单位秒
PREDICT_COUNTER_THRESHOLD = 30
# 历史数据最少条数
MIN_HISTORY_LENGTH = 5000
# 预测步长
PREDICTION_LENGTH = 64
# 陀螺零偏均值阈值 °/h
GYRO_MEAN_THRESHOLD = 0.002
# 陀螺零偏方差阈值 °/h
GYRO_VAR_THRESHOLD = 0.001
# 加表零偏均值阈值 μg
ACC_MEAN_THRESHOLD = 50.0
# 加表零偏方差阈值 μg
ACC_VAR_THRESHOLD = 20.0


# 滑环
# 额定寿命
SLIP_RING_TOTAL_LIFE = 10000000
# 测角关键字
SLIP_RING_ANGLE_FIELD = "GXZZYSSJZTJ1"
# 关机阈值，低于此值不累计
SLIP_RING_SHUTDOWN_THRESHOLD = 10.0
# 半圈
SLIP_RING_HALF_TURN_DEGREE = 180.0
# 阈值
SLIP_RING_THRESHOLD_RATIO = 0.1


# 电池
# 离线接口电压阈值
BATTERY_VOLTAGE_THRESHOLD = 20.0
# 额定
BATTERY_DESIGN_LIFE = 1095
# 阈值
BATTERY_WARNING_DAYS = 182


# 维修映射表（通道索引, GZYY值） -> 器材清单
FAULT_MAP = {
    # ===== 索引0：激光惯导无输出 =====
    (0, "电源装置无信号"): [
        "惯性电源，紧固件套包",
    ],
    (0, "电源装置无信号或惯性装置无信号"): [
        "惯性电源，紧固件套包",
        "惯性测量组件，紧固件套包",
        "导航解算模块，紧固件套包",
        "测角与控制模块，紧固件套包",
    ],
    (0, "惯性装置无信号"): [
        "惯性测量组件，紧固件套包",
        "导航解算模块，紧固件套包",
        "测角与控制模块，紧固件套包",
    ],
    (0, "显控发送装置无信号"): [
        "CPCI导航解算模块，紧固件套包",
        "主处理模块，紧固件套包",
        "串口模块，紧固件套包",
    ],

    # ===== 索引1：激光惯导精度指标超差 =====
    (1, "IMU性能下降"): [
        "惯性测量组件，紧固件套包",
    ],

    # ===== 索引3：单轴调制单元不工作 =====
    (3, "伺服电源故障"): [
        "伺服电源，紧固件套包",
    ],

    # ===== 索引4：单轴调制单元误动作 =====
    (4, "激磁电源故障"): [
        "激磁电源，紧固件套包",
    ],
    (4, "测角与控制模块故障或电机驱动模块故障"): [
        "测角与控制模块，紧固件套包",
        "电机驱动模块，紧固件套包",
    ],

    # ===== 索引5：电源模块不输出 =====
    (5, "惯性电源故障"): [
        "惯性电源，紧固件套包",
    ],
    (5, "激磁电源故障"): [
        "激磁电源，紧固件套包",
    ],
    (5, "程控电源故障"): [
        "程控电源，紧固件套包",
    ],
    (5, "伺服电源故障"): [
        "伺服电源，紧固件套包",
    ],
    (5, "UPS电源故障"): [
        "UPS电源，紧固件套包",
    ],
}


# 航姿跳变（索引2）
HANGZI_FAULT = "航姿跳变"
HANGZI_MATERIALS = [
    "测角与控制模块，紧固件套包",
    "旋变机构，紧固件套包",
]


FAULT_NAME_MAP = {
    0: "激光惯导无输出信号",
    1: "定位精度差",
    2: "航姿跳变",
    3: "单轴调制单元不工作",
    4: "单轴调制单元误动作",
    5: "电源模块不输出",
}


# 更换判断阈值（已用时间 < 此值，说明换了新件）
REPLACE_THRESHOLD_DAYS = 100
REPLACE_THRESHOLD_YEARS = 100 / 365          # 约 0.274 年
REPLACE_THRESHOLD_ROTATIONS = 10000           # 滑环换新阈值（圈）

# Invoke-RestMethod -Uri "http://127.0.0.1:8091/equipForecast/point/data/interialEquip" -Method Post -ContentType "application/json" -InFile "req_status1.json"
