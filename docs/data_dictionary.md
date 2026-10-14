# 输出字段字典

时间采用 ISO8601 `+08:00`；区间为左闭右开。CSV 中空值不等于零。单位由请求固定，并核验 API 返回单位。

## 小时表 weather_hourly.csv

| 字段 | 含义 |
|---|---|
| interval_start / interval_end | 本行覆盖的北京时间小时区间 |
| state_source_time | 气温等瞬时字段的来源时间，等于 interval_start |
| precipitation_source_time | 降水来源时间，等于 interval_end；接口原值覆盖前一小时 |
| temperature_c | 2米气温，°C，小时起点值 |
| relative_humidity_pct | 2米相对湿度，% |
| wind_speed_ms | 10米风速，m/s |
| wind_gusts_ms | 10米阵风，m/s，依接口 IFS/ERA5 时点定义 |
| cloud_cover_pct | 云量，% |
| weather_code | WMO 类别代码，不能当作连续数值求均值 |
| weather_category | 晴、云、雾、毛毛雨、冻降水、雨、雪、雷暴等英文类别 |
| precipitation_mm | 本小时总降水，mm，包含雨雪等水当量 |
| rain_mm | 本小时液态降雨，mm；是总降水的一部分，不与总降水相加 |

## 半小时表 weather_30min.csv

| 字段 | 含义 |
|---|---|
| slot_start / slot_end | 半小时区间，用 slot_start 对齐单车表 |
| state_source_time | 当前小时起点；该时点值保持到两个半小时窗口 |
| precipitation_source_time | 所属小时的结束时点 |
| precipitation_interval_start / precipitation_interval_end | 原始小时降水的覆盖区间 |
| temperature_c / relative_humidity_pct / wind_speed_ms / wind_gusts_ms / cloud_cover_pct | 所属小时起点的瞬时值，单位同小时表 |
| weather_code / weather_category | 所属小时起点的类别 |
| precipitation_hour_mm / rain_hour_mm | 原始小时累计量，在两个半小时窗口重复出现，仅作为小时背景；不能直接跨半小时行求和 |
| precipitation_30min_est_mm / rain_30min_est_mm | 可选均分估计量，mm；默认空，uniform 模式下为小时量一半，可求和但须标注估计 |
| state_mapping | 固定 hold_hour_start |
| rainfall_mapping | 默认 hourly_context_only；均分选项为 uniform_split_estimate |

## 日表 weather_daily.csv

| 字段 | 含义 |
|---|---|
| date / hours | 北京时间日期及完整小时数（24） |
| temperature_mean_c | 当天24个小时起点气温均值，°C |
| temperature_min_hourly_c / temperature_max_hourly_c | 小时采样最低/最高气温，°C，不等于连续观测的日极值 |
| relative_humidity_mean_pct / cloud_cover_mean_pct | 小时值的日均湿度、云量，% |
| precipitation_sum_mm / rain_sum_mm | 当天覆盖区间内的小时累计量之和，mm，末小时使用次日零点记录 |
| precipitation_hours | 总降水大于0的小时区间数，不是降雨持续时长的精确测量 |
| wind_speed_mean_ms | 小时风速均值，m/s |
| wind_gusts_max_hourly_ms | 小时阵风值最大值，m/s |
| weather_category_mode | 小时类别众数；平票选当天最先出现的类别，不是 API 的最严重天气日代码 |

## 元数据与质量报告

`metadata.json` 包含请求模型/坐标/日期、坐标转换方法、数值残差、实际返回格点、捕获时间、原始数据哈希、单位和输出文件哈希。`quality_report.json` 中原始小时数默认为 2,064（含缓冲）；`derived_counts` 才是研究期的 2,016/4,032/84 行。
