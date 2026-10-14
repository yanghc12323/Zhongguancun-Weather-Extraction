# 中关村历史天气数据工具

为共享单车课程项目获取中关村区域天气，自动处理 GCJ-02→WGS84、小时累计降水的时间区间，以及半小时单车窗口的连接。Python 3.10 及以上，仅使用标准库；直接运行不需要 pip 安装。

默认研究期为北京时间 **2026-03-02—2026-05-24**，共 84 天。主要来源是 Open-Meteo 的 ECMWF IFS 历史格点数据，可切换 ERA5。数据属于区域天气估计，不是中关村气象站实测。正式研究区域中心已按 722 个 GCJ-02 区域点计算，配置及来源文件哈希见 `zgc_weather/study_region.json`。

## 快速运行

从 GitHub 获取代码：

```powershell
git clone https://github.com/yanghc12323/Zhongguancun-Weather-Extraction.git
cd Zhongguancun-Weather-Extraction
python -m zgc_weather
```

在本文件所在文件夹打开终端：

```powershell
python -m zgc_weather
```

首次运行需要访问公开网络，不需要 API key。此后相同请求会读取缓存。默认生成：

```text
data/ecmwf_ifs/
├── raw/                  # 原始 API 响应、请求参数、抓取时间和 SHA256
├── weather_hourly.csv    # 2,016 行，按小时区间整理
├── weather_30min.csv     # 4,032 行，用 slot_start 与单车表连接
├── weather_daily.csv     # 84 行日汇总
├── metadata.json         # 坐标、来源、映射方法、单位及输出文件哈希
└── quality_report.json   # 连续性、缺失、重复、取值及汇总核对
```

CSV 使用 UTF-8 BOM，便于 Excel 打开。全部时间字段带 `+08:00`；`--end` 是含当天的日期。下载请求自动向前、向后各加一天，默认原始数据 86 天、2,064 小时；输出只保留研究期。

常用命令：

```powershell
# 显式指定研究日期和输出目录
python -m zgc_weather --start 2026-03-02 --end 2026-05-24 --output data/ecmwf_ifs

# 离线重跑，不联网；输出另存
python -m zgc_weather --cache-dir data/ecmwf_ifs/raw --offline --output data/offline_copy

# 下载 ERA5 对照数据
python -m zgc_weather --model era5

# 可选：按小时内均匀降水假设生成半小时估计量
python -m zgc_weather --cache-dir data/ecmwf_ifs/raw --offline --rain-method uniform --output data/uniform_estimate

# 自定义地点必须成对提供坐标，并声明坐标系
python -m zgc_weather --latitude 39.98 --longitude 116.31 --crs WGS84 --output data/custom

# 需要重新抓取时，显式更新同一请求的缓存
python -m zgc_weather --refresh

python -m zgc_weather --help
```

## 坐标如何处理

接口参数采用 WGS84。默认输入中心是 GCJ-02 纬度 `39.9759376731302`、经度 `116.3213781163435`，迭代反解后请求点约为 WGS84 纬度 `39.97464779`、经度 `116.31526461`。

算法采用公开近似前向公式的数值反解，并通过北京、上海、深圳的公开参考坐标检查。数值往返残差只说明公式求解收敛，不代表官方测绘精度。原始区域点保留到三位小数，中心的较多小数位来自平均计算。程序仅转换天气请求点，保留原单车坐标约定。

API 返回的格点可偏离请求点。约 9 km 的 IFS 网格和约 25 km 的 ERA5 网格无法提供每个单车 geohash 的独立实测天气。`metadata.json` 同时记录输入点、转换后请求点和实际返回格点。

## 时间对齐如何处理

小时表的每行是 `[interval_start, interval_end)`：

- 气温、湿度、风速、阵风、云量、天气代码使用小时起点的记录。
- `precipitation_mm` 和 `rain_mm` 使用小时终点的记录，因为接口累计的是时间戳之前一小时。例如 09:00 的降水属于 08:00—09:00；5 月 25 日 00:00 的降水属于研究期最后一小时。
- 日降水按上述区间汇总；日温度极值来自小时采样，并不是原生气象日内连续极值。天气类别使用小时类别众数，平票取当天最先出现的类别，不把天气代码求均值。

半小时表每行是 `[slot_start, slot_end)`。瞬时量使用该小时起点值，00:00 和 00:30 的气温因此相同，方法标记为 `hold_hour_start`。默认保留 `precipitation_hour_mm`、`rain_hour_mm` 及其小时覆盖区间；这两个字段是共享的小时背景，**不能把两行的小时雨量相加当作一小时总量**。

默认 `precipitation_30min_est_mm`、`rain_30min_est_mm` 为空。只有 `--rain-method uniform` 才把小时雨量各分一半，并标记 `uniform_split_estimate`。均分保证总量守恒，却不能恢复真实半小时降雨分布。

详细字段见 [字段字典](docs/data_dictionary.md)。

## 与单车数据连接

本项目单车时间键为 `slot_start`。可使用独立的 CSV 连接命令：

```powershell
python -m zgc_weather.join --bike-csv path/to/bike_panel.csv --weather-csv data/ecmwf_ifs/weather_30min.csv --output data/bike_with_weather.csv
```

每个半小时时间戳只对应一条区域天气，允许多个 geohash 共用该行。原有单车行、列和值会保留，新增列统一带 `weather_` 前缀。单车无时区的时间按北京时间解释；带时区时间会换算到北京时间。不会进行模糊匹配或最近邻填补，天气重复键、未匹配时间、列名冲突会报错。

若原单车表为 Parquet，可在原分析环境先导出 CSV，或直接使用该环境的 pandas：

```python
import pandas as pd

bike = pd.read_parquet("path/to/bike_panel.parquet")
weather = pd.read_csv("data/ecmwf_ifs/weather_30min.csv")
# 原项目 slot_start 为北京时间的无时区时间：先明确本地时区。
bike["slot_start"] = pd.to_datetime(bike["slot_start"]).dt.tz_localize("Asia/Shanghai")
weather["slot_start"] = pd.to_datetime(weather["slot_start"])
joined = bike.merge(weather, on="slot_start", how="left", validate="many_to_one")
assert len(joined) == len(bike)
assert joined["temperature_c"].notna().all()
```

Parquet/pandas 不是本工具的运行依赖；上例供已有分析环境使用。若单车时间本来带时区，用 `tz_convert`，不能再次 `tz_localize`。

## 质量检查与复现

```powershell
python -m unittest discover -s tests -v
```

测试不联网，覆盖参考坐标、跨日降水、累计量守恒、缺失/重复/单位错误、缓存校验、重试、命令行输出和多对一连接。GitHub Actions 已配置 Windows/Ubuntu 的 Python 3.10/3.12 测试矩阵；本地运行结果不等于远程 CI 已执行。

真实抓取另经全窗口运行、离线重跑和输出哈希比较。校验失败返回非零状态并留下质量报告；不会新生成天气表。若输出目录已有旧表，旧表仍保留，只有本次运行退出码为 0、质量报告通过且哈希与 metadata 一致的输出才应使用。

第一版具体结果见 [验证记录](docs/verification.md)。本地另有 `data/region30_with_weather.csv`，为现有 V8 区域半小时序列的连接验证结果，4,032 行全部匹配；原 V8 文件保持原位。

缓存按请求参数和接口地址的哈希命名，保留首次抓取时间和响应 SHA256。历史产品也可能修订；缓存可固定本次研究快照，`--refresh` 表示有意获取新版本。程序只支持固定北京时间，未实现其他时区或夏令时研究。

## 研究使用与 GitHub 打包

当前天气表用于事后描述和探索。事后历史天气、再分析及半小时行中覆盖至未来整点的小时降水，可能在真实预测时尚不可得。评价提前预测时，需要另行接入按发布时间筛选的预报或当时可得的观测。

仓库地址：[Zhongguancun-Weather-Extraction](https://github.com/yanghc12323/Zhongguancun-Weather-Extraction)。仓库包含包目录、测试、README、`docs/`、`NOTICE`、`pyproject.toml`、`.gitignore` 和 `.github/`。`data/`、`_validation/`、`dist/` 已忽略，本地规划日志也不必放入交付代码包。工具没有依赖课程原始骑行文件、开发者绝对路径或账户信息；其他人可以按快速运行命令自行获取天气数据。

天气数据署名建议：**Weather data: Open-Meteo and ECMWF (IFS/ERA5), CC BY 4.0; processed and time-aligned for this course project.** 原创代码的公开许可可由小组发布时确定；复用算法的许可通知已保存在 NOTICE，随代码保留。

## 来源

- [Open-Meteo 历史天气接口、坐标及时间字段说明](https://open-meteo.com/en/docs/historical-weather-api)
- [Open-Meteo 使用条款与数据署名要求](https://open-meteo.com/en/terms)
- [Open-Meteo 历史预报接口](https://open-meteo.com/en/docs/historical-forecast-api)
- [eviltransform 坐标参考与测试向量](https://github.com/googollee/eviltransform)
- [coordtransform 椭球常数对照](https://github.com/wandergis/coordtransform)
