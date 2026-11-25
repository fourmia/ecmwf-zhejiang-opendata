# 代码与文档审查记录（2026-11-19）

> **审查范围**: main @ 3265f21 全部代码与 docs/，交叉对照本地实测数据
> （D1D 分发样本 + ECMWF Open Data 0p1 实际下载）与 eccodes 2.50.1 官方参数库。
> **方法**: 所有结论均附本地可复现证据；断网项明确标注"待在线核实"。
> **关联资产**: `verify/`（D1D 同源性验证脚本与报告，本地未入库，GRIB 数据不入库）。

---

## 一、背景：D1D 同源性验证结论（已完成，实测）

对 `E:\项目测试\d1d\d1d\` 的 ECMWF D1D 对华 GTS 分发产品（GRIB1）与
Open Data 0p1（GRIB2，GCS 官方桶下载）做了 2026-11-16 00z 同起报逐格点对比：

1. **同源确认**：共同步长（3/6/9h）地面 msl/sp **100% 逐点全等**；
   2t/2d/风/tp/云量最大差值恰等于 open data CCSDS 打包量化步长的一半
   （0.125 K、0.015625 m/s、2⁻¹⁴ m 等）——同一份数值、不同打包精度的数学特征。
2. **格点严格一致**（地面）：两边均锚定整度数 + 0.1° 增量，实测坐标差 ~1e-12°。
3. **高空分辨率不同**：D1D 压力层 **0.2°**（4 文件 ×171 条消息全量扫描），
   open data 0.1°。重合点（零插值）数值也不全等（t RMSE≈0.1 K、风≈0.3 m/s、
   全等比例 0%），源于两条不同的原生网格插值链——**同源但不同值，不可混用**。
4. D1D 规格：逐小时 0–10h，每文件一步长；地面 0.1°（70°N–10°S, 40°E–180°E），
   高空 0.2°（90°N–20°S, 0–180°E）；要素清单见 `verify/D1D_inventory.md`（本地）。

## 二、对早期口头/报告信息的更正

| # | 早期说法 | 更正后 | 依据 |
|---|---|---|---|
| A1 | 0p1 地面 21 个变量 | **45 个**（21 为脚本默认子集） | docs 源1 index 声称 + 参数库核对 shortName 均存在 |
| A2 | 06/18z 到 144h | **0–90h / 3h / 31 步** | DATA_CHANNEL_SPEC 实测记录 |
| A3 | full=0–240h | **0–360h / 85 步** | VERIFICATION_360H 实测记录 |
| A4 | pl=6 变量×12 层 | 文档称 **10×14**，但其中 `gh` 存疑（见 C7） | 待 index 裁决 |

> 注：A1–A3 采信仓库文档的实测记录；A4 因 C7 发现文档元数据错误而降级为"待核实"。

## 三、已确认问题（本地证据）

### C1 🔴 上线日期自相矛盾（待在线裁决）
- `README.md` / `docs/ecmwf_parameters.md`：0.1° 上线 **2026-10-20**
- `docs/VERIFICATION_360H.md` L23：0.1° 发布 "**2024年10月**"
- 两者必有一错。审查时 GCS / api.github.com / confluence 均不可达，无法查官方页面。

### C2 🔴 "eccodes 不能用 pip 装" 说法错误
- `README.md` 与 `src/requirements.txt` 均称 eccodes 必须系统包管理器安装。
- **实证**：本项目 `.venv` 由 `uv pip install eccodes` 安装（wheel 2.40.1，
  自带 `eccodes.dll` 库版本 **2.50.1** + `aec.dll`），Windows 下完成全部
  GRIB1/GRIB2（含 CCSDS）解码与验证。
- 建议改为："推荐 pip/uv 安装（wheel 自带库）；系统包管理器亦可"。

### C3 🟡 DATA_CHANNEL_SPEC §2.1 cron 注释四条全部错位
代码模拟 `infer_run_time(lag=8)` 实测：

| CST 触发 | 实际取批次 | 文档注释（错误） |
|---|---|---|
| 13:00 | 前一天 **18z** | "追 00z" |
| 19:00 | 当天 **00z** | "追 06z" |
| 01:00 | 前一天 **06z** | "追 12z" |
| 07:00 | 前一天 **12z** | "追 18z" |

文档自身的推算表正确，注释与表矛盾。另：`--lag-hours 8` 相对实测发布延迟
9–11h 偏乐观，触发时目标批次可能尚未发布（404），建议 lag≥10 或依赖重试。

### C4 🟢 累计量处理范围（风险低于最初评估）
- `RAD_ACCUM_VARS` 仅含 5 个辐射变量；`--extra` 下载的 tp/cp/sf/ro/ewss/nsss
  不做差分（设计如此）。
- **实证**：cfgrib 输出保留 `GRIB_stepType='accum'` 属性（tp 实测），元数据
  并未丢失。建议在文档中明示"除辐射外其余累计量原样保留，见 attrs"。

### C5 🟢 RAD_DOWNWARD_VARS 语义瑕疵
`ssr` 官方名为 "Surface **net** short-wave (solar) radiation"（净短波），
归入"向下辐射"注释不准确；clip≥0 物理上基本成立，可保留但应改注释。

### C6 🟢 文本残留
- `src/download_ecmwf.py` docstring：L19 "默认 … AWS S3"（实际默认 google）、
  L25 "完整10天预报"（full 现为 0–360h/15天）。
- `docs/ecmwf_parameters.md` 附录B："应输出 21 个核心变量" 与正文 45 个易混淆
  （21 为默认下载子集，应写明）。
- 源3 格点数 50×54 与逐点验证的 51×55 不一致（bbox 端点取舍约定不同，建议写明）。

### C7 🔴 参数表多处失实（eccodes 2.50.1 官方参数库裁决）

`docs/ecmwf_parameters.md` "源2" 列至少 7 处错误：

| 文档声称 | 官方参数库实际 |
|---|---|
| sve/svn = 东向/北向**有效波高**，228033/228034 | **海面流速** Eastward/Northward surface sea water velocity (m/s)，**262140/262139**；228034=fcpc（对流降水覆盖比），228033 不存在 |
| zos = 263090 | **262124** Sea surface height |
| sithick = 228029 | **262000**；228029 = i10fg（瞬时10米阵风） |
| sot = 228139 | **260360**；228139 不存在 |
| vsw = 39 | **260199**；39 = swvl1 |
| tcrw = 228088 | **228089** |
| pl 层 gh = 156 = Geopotential height (gpm) | **GRIB2 中 156/gh → Orography（地形, m）**；GRIB1 中 gh=156=gpm 成立（D1D 即 GRIB1） |

**复现命令**（离线，pip 版 eccodes 即可）：

```python
import eccodes as ec
h = ec.codes_grib_new_from_samples('GRIB2')
ec.codes_set(h, 'shortName', 'sve')
print(ec.codes_get(h, 'paramId'), ec.codes_get(h, 'name'))
# 262140 Eastward surface sea water velocity
```

**影响**：
1. "三重来源交叉验证"声明的可信度受损：shortName 清单（源1）可能仍正确，
   但 paramId/英文名/单位列不可直接引用。
2. **pl "10 变量含 gh" 存疑**：GRIB2 语义下 gh=地形，不应出现在压力层；
   0p1 pl 实际变量集需 index 原文 + 实下载裁决。
3. §1.12 "海浪" 一节若 sve/svn 属实则为**海流**要素，要素选择建议需改写。

## 四、待在线核实清单（网络恢复后执行）

- [ ] 拉取 `…/ifs/0p1/oper/*-sfc.index` / `*-pl.index`，核对 45/10 清单与 levtype
- [ ] 实际请求 pl `gh`、sfc `sve`/`svn`/`zos`，读出 paramId/name 一锤定音
- [ ] 官方 Confluence 裁决 0.1° 上线日期（C1）
- [ ] 扩展 D1D↔open data 高空对比至 w/d/vo 与 10/50 hPa 层

## 五、建议修复顺序

1. C7/C1：事实错误，先核实后改文档（参数表以 eccodes 参数库重建，可离线生成）
2. C2/C3：误导部署与业务踩坑，纯文本修复
3. C4/C5/C6：注释与文档澄清

—— 记录人：pi 审查会话（证据与脚本存于本地 `verify/`）
