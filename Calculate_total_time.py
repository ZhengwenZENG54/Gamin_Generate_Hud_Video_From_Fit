import pandas as pd
import numpy as np
import os

def calculate_total_time(
    lap_total_time=3600,
    alpha_hud_fps=30,
    alpha_map_fps=5,
    alpha_elev_fps=5,
    beta_time_fps=1,
    beta_dist_fps=5,
    beta_elev_fps=5
):
    """
    根据输入的7个参数计算总耗时。
    
    参数:
        lap_total_time: Lap总时长 (秒)
        alpha_hud_fps: Alpha_HUD 帧率
        alpha_map_fps: Alpha_map帧率
        alpha_elev_fps: Alpha_elev帧率
        beta_time_fps: Beta_time帧率
        beta_dist_fps: Beta_dist帧率
        beta_elev_fps: Beta_elev帧率
    
    返回:
        总耗时 (秒)
    """
    
    excel_path = r"E:\Desktop\Gamin_Generate_Hud_Video_From_Fit\Gamin_Generate_Hud_Video_From_Fit\fit_video_audit_log.xlsx"
    
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel文件不存在: {excel_path}")
    
    try:
        # 读取Excel文件
        df = pd.read_excel(excel_path, usecols="C:L", header=0)
    except Exception as e:
        raise RuntimeError(f"无法读取Excel文件: {e}")
    
    # 重命名列以匹配描述
    column_names = [
        'Lap总时长', 'Alpha_HUD帧率', 'Alpha_map帧率', 'Alpha_elev帧率',
        'Alpha耗时', 'Beta_time帧率', 'Beta_dist帧率', 'Beta_elev帧率',
        'Beta耗时', '总耗时'
    ]
    df.columns = column_names
    
    # 将所有空值替换为0
    df = df.fillna(0)
    
    # 确保数据为数值类型
    for col in column_names:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    print(f"✓ 成功读取Excel文件，共 {len(df)} 行原始数据")
    
    # ===== 业务规则处理 =====
    print("\n🔄 应用业务规则...")
    
    # 规则1: Alpha有数据但Alpha耗时为0，且Beta无数据时，用总耗时代替Alpha耗时
    alpha_rule_count = 0
    for i in range(len(df)):
        if (
            (df.loc[i, 'Alpha_HUD帧率'] > 0 or 
             df.loc[i, 'Alpha_map帧率'] > 0 or 
             df.loc[i, 'Alpha_elev帧率'] > 0) and 
            df.loc[i, 'Alpha耗时'] == 0
        ):
            if (
                df.loc[i, 'Beta_time帧率'] == 0 and 
                df.loc[i, 'Beta_dist帧率'] == 0 and 
                df.loc[i, 'Beta_elev帧率'] == 0
            ):
                df.loc[i, 'Alpha耗时'] = df.loc[i, '总耗时']
                alpha_rule_count += 1
    
    # 规则2: Beta有数据但Beta耗时为0，且Alpha无数据时，用总耗时代替Beta耗时
    beta_rule_count = 0
    for i in range(len(df)):
        if (
            (df.loc[i, 'Beta_time帧率'] > 0 or 
             df.loc[i, 'Beta_dist帧率'] > 0 or 
             df.loc[i, 'Beta_elev帧率'] > 0) and 
            df.loc[i, 'Beta耗时'] == 0
        ):
            if (
                df.loc[i, 'Alpha_HUD帧率'] == 0 and 
                df.loc[i, 'Alpha_map帧率'] == 0 and 
                df.loc[i, 'Alpha_elev帧率'] == 0
            ):
                df.loc[i, 'Beta耗时'] = df.loc[i, '总耗时']
                beta_rule_count += 1
    
    # 规则3: 如果Alpha耗时和Beta耗时都为0，但总耗时不为0，则按比例分配
    # 这里我们假设Alpha和Beta各占50%，除非有其他信息
    allocation_count = 0
    for i in range(len(df)):
        if (
            df.loc[i, 'Alpha耗时'] == 0 and 
            df.loc[i, 'Beta耗时'] == 0 and 
            df.loc[i, '总耗时'] > 0
        ):
            # 如果Alpha有帧率数据，则分配一部分给Alpha
            if (
                df.loc[i, 'Alpha_HUD帧率'] > 0 or 
                df.loc[i, 'Alpha_map帧率'] > 0 or 
                df.loc[i, 'Alpha_elev帧率'] > 0
            ):
                df.loc[i, 'Alpha耗时'] = df.loc[i, '总耗时'] * 0.5
                df.loc[i, 'Beta耗时'] = df.loc[i, '总耗时'] * 0.5
                allocation_count += 1
    
    print(f"  应用Alpha规则: {alpha_rule_count} 行")
    print(f"  应用Beta规则: {beta_rule_count} 行")
    print(f"  应用分配规则: {allocation_count} 行")
    
    # 移除全为0的行（但保留那些通过规则填充的行）
    df_valid = df[
        (df['Alpha耗时'] > 0) | 
        (df['Beta耗时'] > 0) | 
        (df['总耗时'] > 0)
    ].copy()
    
    valid_rows = len(df_valid)
    print(f"✓ 有效数据行数: {valid_rows}")
    
    if valid_rows < 2:
        raise ValueError("Excel中的数据点不足，无法进行拟合。至少需要2个有效数据点。")
    
    # ---------- 拟合Alpha部分的常数 ----------
    print("\n📈 拟合Alpha部分常数...")
    
    # 准备Alpha数据
    X_alpha = np.column_stack([
        df_valid['Lap总时长'] * df_valid['Alpha_HUD帧率'],
        df_valid['Lap总时长'] * df_valid['Alpha_map帧率'],
        df_valid['Lap总时长'] * df_valid['Alpha_elev帧率'],
        np.ones(valid_rows)
    ])
    y_alpha = df_valid['Alpha耗时'].values
    
    # 过滤掉y=0的数据点
    alpha_mask = y_alpha > 0
    X_alpha_valid = X_alpha[alpha_mask]
    y_alpha_valid = y_alpha[alpha_mask]
    
    if len(y_alpha_valid) < 2:
        raise ValueError(f"Alpha部分有效数据不足，需要至少2条，实际只有{len(y_alpha_valid)}条")
    
    # 使用最小二乘法求解
    try:
        coeffs_alpha, residuals_alpha, rank_alpha, s_alpha = np.linalg.lstsq(X_alpha_valid, y_alpha_valid, rcond=None)
    except np.linalg.LinAlgError:
        raise ValueError("Alpha部分拟合失败：数据矩阵奇异或秩不足")
    
    A_HUD, A_map, A_elev, A = coeffs_alpha
    
    # 计算Alpha拟合的R²值
    y_alpha_pred = X_alpha_valid @ coeffs_alpha
    ss_res_alpha = np.sum((y_alpha_valid - y_alpha_pred) ** 2)
    ss_tot_alpha = np.sum((y_alpha_valid - np.mean(y_alpha_valid)) ** 2)
    r_squared_alpha = 1 - (ss_res_alpha / ss_tot_alpha) if ss_tot_alpha != 0 else 0
    
    # ---------- 拟合Beta部分的常数 ----------
    print("📈 拟合Beta部分常数...")
    
    # 准备Beta数据
    X_beta = np.column_stack([
        df_valid['Lap总时长'] * df_valid['Beta_time帧率'],
        df_valid['Lap总时长'] * df_valid['Beta_dist帧率'],
        df_valid['Lap总时长'] * df_valid['Beta_elev帧率'],
        np.ones(valid_rows)
    ])
    y_beta = df_valid['Beta耗时'].values
    
    # 过滤掉y=0的数据点
    beta_mask = y_beta > 0
    X_beta_valid = X_beta[beta_mask]
    y_beta_valid = y_beta[beta_mask]
    
    if len(y_beta_valid) < 2:
        raise ValueError(f"Beta部分有效数据不足，需要至少2条，实际只有{len(y_beta_valid)}条")
    
    # 使用最小二乘法求解
    try:
        coeffs_beta, residuals_beta, rank_beta, s_beta = np.linalg.lstsq(X_beta_valid, y_beta_valid, rcond=None)
    except np.linalg.LinAlgError:
        raise ValueError("Beta部分拟合失败：数据矩阵奇异或秩不足")
    
    B_time, B_dist, B_elev, B = coeffs_beta
    
    # 计算Beta拟合的R²值
    y_beta_pred = X_beta_valid @ coeffs_beta
    ss_res_beta = np.sum((y_beta_valid - y_beta_pred) ** 2)
    ss_tot_beta = np.sum((y_beta_valid - np.mean(y_beta_valid)) ** 2)
    r_squared_beta = 1 - (ss_res_beta / ss_tot_beta) if ss_tot_beta != 0 else 0
    
    # ---------- 打印拟合常数 ----------
    print("\n" + "="*70)
    print("📊 拟合常数结果:")
    print("="*70)
    
    print(f"\n🔹 Alpha部分常数 (R² = {r_squared_alpha:.4f}):")
    print(f"  A_HUD  = {A_HUD:.10e}")
    print(f"  A_map  = {A_map:.10e}")
    print(f"  A_elev = {A_elev:.10e}")
    print(f"  A      = {A:.10e}")
    
    print(f"\n🔹 Beta部分常数 (R² = {r_squared_beta:.4f}):")
    print(f"  B_time = {B_time:.10e}")
    print(f"  B_dist = {B_dist:.10e}")
    print(f"  B_elev = {B_elev:.10e}")
    print(f"  B      = {B:.10e}")
    
    # 验证拟合效果
    print(f"\n🔍 拟合验证:")
    print(f"  Alpha部分: 使用了 {len(y_alpha_valid)}/{valid_rows} 行数据")
    print(f"  Beta部分: 使用了 {len(y_beta_valid)}/{valid_rows} 行数据")
    
    # 计算拟合值与真实值的对比（前5行）
    print(f"\n📋 拟合值 vs 真实值 (前5行):")
    print("-" * 70)
    print(f"{'序号':<4} {'类型':<6} {'真实值':<12} {'拟合值':<12} {'误差':<12}")
    print("-" * 70)
    
    # Alpha部分
    for i in range(min(5, len(y_alpha_valid))):
        true_val = y_alpha_valid[i]
        pred_val = y_alpha_pred[i]
        error = abs(true_val - pred_val)
        print(f"{i+1:<4} {'Alpha':<6} {true_val:<12.2f} {pred_val:<12.2f} {error:<12.2f}")
    
    # Beta部分
    for i in range(min(5, len(y_beta_valid))):
        true_val = y_beta_valid[i]
        pred_val = y_beta_pred[i]
        error = abs(true_val - pred_val)
        print(f"{i+1:<4} {'Beta':<6} {true_val:<12.2f} {pred_val:<12.2f} {error:<12.2f}")
    
    # ---------- 计算总耗时 ----------
    total_time = (
        lap_total_time * (
            alpha_hud_fps * A_HUD +
            alpha_map_fps * A_map +
            alpha_elev_fps * A_elev +
            beta_time_fps * B_time +
            beta_dist_fps * B_dist +
            beta_elev_fps * B_elev
        ) + A + B
    )
    
    # ---------- 显示计算详情 ----------
    print("\n" + "="*70)
    print("🧮 计算详情:")
    print("="*70)
    
    print(f"\n📥 输入参数:")
    print(f"  Lap总时长      = {lap_total_time} 秒")
    print(f"  Alpha_HUD帧率 = {alpha_hud_fps}")
    print(f"  Alpha_map帧率 = {alpha_map_fps}")
    print(f"  Alpha_elev帧率= {alpha_elev_fps}")
    print(f"  Beta_time帧率 = {beta_time_fps}")
    print(f"  Beta_dist帧率 = {beta_dist_fps}")
    print(f"  Beta_elev帧率 = {beta_elev_fps}")
    
    print(f"\n📐 计算公式:")
    print(f"  总耗时 = Lap × (Σ系数×帧率) + A + B")
    
    alpha_contrib = lap_total_time * (alpha_hud_fps * A_HUD + alpha_map_fps * A_map + alpha_elev_fps * A_elev)
    beta_contrib = lap_total_time * (beta_time_fps * B_time + beta_dist_fps * B_dist + beta_elev_fps * B_elev)
    
    print(f"\n📊 贡献分解:")
    print(f"  Alpha部分 = {lap_total_time} × ({alpha_hud_fps}×{A_HUD:.6e} + {alpha_map_fps}×{A_map:.6e} + {alpha_elev_fps}×{A_elev:.6e})")
    print(f"           = {alpha_contrib:.2f} 秒")
    print(f"  Beta部分  = {lap_total_time} × ({beta_time_fps}×{B_time:.6e} + {beta_dist_fps}×{B_dist:.6e} + {beta_elev_fps}×{B_elev:.6e})")
    print(f"           = {beta_contrib:.2f} 秒")
    print(f"  常数项    = {A:.2f} + {B:.2f} = {A + B:.2f} 秒")
    
    print("\n" + "="*70)
    print("🎯 最终结果:")
    print("="*70)
    print(f"\n  总耗时 = {total_time:.2f} 秒")
    print(f"  约合 {total_time/60:.1f} 分钟")
    print(f"  约合 {total_time/3600:.2f} 小时")
    
    return total_time

# 示例使用
if __name__ == "__main__":
    try:
        # 使用你喜欢的参数格式
        result = calculate_total_time(
            lap_total_time=3600,
            alpha_hud_fps=30,
            alpha_map_fps=5,
            alpha_elev_fps=5,
            beta_time_fps=1,
            beta_dist_fps=5,
            beta_elev_fps=5
        )
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()