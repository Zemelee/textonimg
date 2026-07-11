#!/usr/bin/env python3
"""
图片文案叠加工具 (Image Text Overlay)
用于医美/美容机构朋友圈宣传图制作

特性：
  - 默认字体为思源黑体（Source Han Sans SC），字体文件自带于 scripts/fonts/，跨设备即用
  - 逐行独立圆角阴影（短行短阴影、长行长阴影），无逐字描边
  - 多行文案支持手动换行（\\n）与自动折行
  - 文字对齐控制（left 默认 / right / center）
  - 品牌名位置 / 颜色 / 字号独立控制（复用主文案的定位与渲染逻辑）
  - 多行文案之间的可见行间距（--line-gap）独立可调

Usage:
    python image.py \
        --input <input_image_path> \
        --text "文案内容（用 \\n 手动换行）" \
        [--position "100 200"] \
        [--font sh1] \
        [--font-size auto] \
        [--color "#FFFFFF"] \
        [--align left] \
        [--letter-spacing 4] \
        [--line-gap 18] \
        [--padding-x 5] [--padding-y 5] \
        [--brand "YQ"] \
        [--brand-position "200 50"] \
        [--brand-color "#FFFFFF"] \
        [--brand-size auto]

可用字体 (--font):
    sh1 (思源黑体,默认) / sh2 (思源黑体中等) /
    sh3 (思源黑体粗体) / yahei (微软雅黑) /
    kaiti (楷体) / xingshu (开源行书 志莽行书)

位置 (--position / --brand-position):
    auto (智能判断，默认) / "x y" (像素坐标，如 "0 0" 为图片左上角)
"""

import argparse
import os
import sys
import json
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# ============================================================
# 字体配置
# 思源黑体 (Source Han Sans SC) 字体文件自带于 scripts/fonts/
# ============================================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FONT_DIR = os.path.join(_SCRIPT_DIR, "fonts")

FONT_MAP = {
    "sh1": {
        "name": "思源黑体 (Source Han Sans SC)",
        "paths": [
            os.path.join(_FONT_DIR, "SourceHanSansCN-Regular.otf")
        ],
    },
    "sh2": {
        "name": "思源黑体 中等 (Medium)",
        "paths": [
            os.path.join(_FONT_DIR, "SourceHanSansCN-Medium.otf"),
        ],
    },
    "sh3": {
        "name": "思源黑体 粗体 (Bold)",
        "paths": [
            os.path.join(_FONT_DIR, "SourceHanSansCN-Bold.otf"),
        ],
    },
    "yahei": {
        "name": "微软雅黑",
        "paths": [
            os.path.join(_FONT_DIR, "msyh.ttc"),
        ],
    },
    "kaiti": {
        "name": "楷体",
        "paths": [
            os.path.join(_FONT_DIR, "simkai.ttf"),
        ],
    },
    "xingshu": {
        "name": "行书",
        "paths": [
            os.path.join(_FONT_DIR, "ZhiMangXing-Regular.ttf"),
        ],
    },
}


def load_font(font_key: str, size: int = 48) -> ImageFont.FreeTypeFont:
    """加载指定字体，找不到则回退到默认（思源黑体 -> 微软雅黑）"""
    font_info = FONT_MAP.get(font_key, FONT_MAP["sh1"])
    for path in font_info["paths"]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # 全局回退：思源黑体(自带) -> 微软雅黑(系统) -> 位图默认
    for fb in [
        os.path.join(_FONT_DIR, "SourceHanSansCN-Regular.otf"),
        "C:/Windows/Fonts/msyh.ttc",
    ]:
        if os.path.exists(fb):
            try:
                return ImageFont.truetype(fb, size)
            except Exception:
                continue
    return ImageFont.load_default()


def resolve_position(position_str):
    """
    将位置字符串解析为锚点坐标。
    返回 (x, y) 或 None(表示智能判断)。
    """
    if not position_str or position_str == "auto":
        return None

    position_str = position_str.strip().lower()

    # 坐标定位："x y" 格式，如 "0 0" 表示图片左上角
    parts = position_str.split()
    if len(parts) == 2:
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            pass

    return None


def smart_position(img, text_lines, font, line_height=10):
    """智能判断最佳文字放置位置"""
    import statistics

    img_gray = img.convert("L")
    w, h = img.size
    margin_x = int(w * 0.05)
    margin_y = int(h * 0.06)

    candidates = [
        ("bottom-center", (margin_x, int(h * 0.62), w - margin_x, h - margin_y), 1),
        ("bottom-left", (margin_x, int(h * 0.65), int(w * 0.55), h - margin_y), 2),
        ("bottom-right", (int(w * 0.45), int(h * 0.65), w - margin_x, h - margin_y), 3),
        ("top-left", (margin_x, margin_y, int(w * 0.55), int(h * 0.35)), 4),
        ("center", (margin_x, int(h * 0.35), w - margin_x, int(h * 0.65)), 5),
    ]

    def region_complexity(box):
        x1, y1, x2, y2 = box
        region = img_gray.crop((x1, y1, x2, y2))
        pixels = list(region.getdata())
        if not pixels:
            return float("inf")
        try:
            return statistics.stdev(pixels)
        except statistics.StatisticsError:
            return 0

    scored = []
    for name, box, pri in candidates:
        comp = region_complexity(box)
        scored.append((name, box, pri, comp))

    scored.sort(key=lambda x: (x[2], x[3]))
    best_box = scored[0][1]
    anchor_x = (best_box[0] + best_box[2]) // 2
    anchor_y = best_box[3] - 10
    return anchor_x, anchor_y


def wrap_text(text, font, max_width, draw):
    """按像素宽度自动折行，同时支持用 \\n 手动换行（\\n 处强制断行）"""
    if not text:
        return []
    # 命令行传参时无法直接输入真换行，常见写法是 "\n"（反斜杠 n 两个字符）。
    # 这里统一把字面量 "\\n" 转成真正的换行符，避免 \n 被当成文字画到图上。
    text = text.replace("\\n", "\n")

    # 先按显式换行符拆分成段落，每段再按宽度自动折行
    paragraphs = text.split("\n")
    lines = []
    for para in paragraphs:
        if para == "":
            lines.append("")
            continue
        current_line = ""
        for char in para:
            test_line = current_line + char
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char
        if current_line:
            lines.append(current_line)
    return lines


def draw_text_block(text_layer, draw, lines, font, anchor_x, start_y, line_height,
                    anchor="mm", text_color="#FFFFFF", block_color=(0, 0, 0),
                    block_alpha=100, shadow=True, shadow_alpha=60,
                    padding_x=26, padding_y=26,
                    radius=20, blur=10, solid_block=True, letter_spacing=0,
                    text_align="left", box_height=None):
    """
    绘制文字块：逐行绘制独立阴影（每行阴影长度跟随该行文字宽度），
    再画无描边的纯色文字。
    支持 letter_spacing 字间距（逐字绘制）。
    支持 text_align: "left"(默认) / "right"，控制文字左对齐还是右对齐。

    注意：anchor 参数控制整体水平定位参考点（lm=左锚点/rm=右锚点/mm=居中锚点），
    text_align 控制多行文字的对齐方式。两者配合使用：
      - 左对齐 + lm 锚点：所有行左边缘对齐到 anchor_x
      - 右对齐 + rm 锚点：所有行右边缘对齐到 anchor_x
      - 居中 + mm 锚点：每行各自居中对齐于 anchor_x（已有行为）
    """
    if not lines:
        return text_layer

    # 计算每行宽度（含字间距）
    line_widths = []
    for ln in lines:
        if letter_spacing and len(ln) > 1:
            w_total = 0
            for ch in ln:
                bbox = draw.textbbox((0, 0), ch, font=font)
                w_total += (bbox[2] - bbox[0]) + letter_spacing
            w_total -= letter_spacing  # 末尾不加间距
        else:
            bbox = draw.textbbox((0, 0), ln, font=font)
            w_total = bbox[2] - bbox[0]
        line_widths.append(w_total)

    n = len(lines)
    W, Ht = text_layer.size

    # 每行阴影盒高度：默认等于行步进高度（旧行为）；
    # 若 caller 传入 box_height，则阴影盒保持紧凑，行间距由 line_height 单独控制。
    if box_height is None:
        box_height = line_height

    # --- 逐行绘制独立阴影和背景 ---
    for i, line in enumerate(lines):
        ly = start_y + i * line_height
        line_w = line_widths[i]

        # 空行（如连续换行符产生）：仅占位，不绘制阴影/背景
        if not line.strip():
            continue

        # 根据锚点和对齐方式计算本行 x 起始坐标
        if anchor == "mm":
            cx = anchor_x - line_w // 2
        elif anchor == "rm":
            # 右锚点：行的右边缘在 anchor_x
            cx = anchor_x - line_w
        else:  # lm 或其他，默认左对齐起始
            cx = anchor_x

        # 右对齐覆盖：当 text_align="right" 时重新计算每行的 x
        if text_align == "right":
            if anchor == "mm":
                cx = anchor_x - line_w // 2
            elif anchor == "lm":
                cx = anchor_x + (max(line_widths) - line_w) if line_widths else cx
            elif anchor == "rm":
                cx = anchor_x - line_w
            else:
                cx = anchor_x - line_w

        # 本行阴影/背景的像素范围（阴影盒高度用紧凑的 box_height，行间留白用 line_height 控制）
        line_top = ly - box_height // 2
        line_bottom = ly + box_height // 2
        bx = int(cx - padding_x)
        by = int(line_top - padding_y)
        bx2 = int(cx + line_w + padding_x)
        by2 = int(line_bottom + padding_y)

        # 裁剪到图层边界
        px0c = max(0, bx)
        py0c = max(0, by)
        px1c = min(W, bx2)
        py1c = min(Ht, by2)

        # 本行柔和投影（逐行独立阴影）
        if shadow:
            shadow_layer = Image.new("RGBA", (W, Ht), (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shadow_layer)
            sdraw.rounded_rectangle(
                [px0c, py0c, px1c, py1c], radius=radius, fill=(0, 0, 0, shadow_alpha)
            )
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
            text_layer = Image.alpha_composite(text_layer, shadow_layer)
            draw = ImageDraw.Draw(text_layer)

        # 本行半透明磨砂面板（可选）
        if solid_block:
            draw.rounded_rectangle(
                [px0c, py0c, px1c, py1c], radius=radius,
                fill=block_color + (block_alpha,),
            )

    # --- 纯色文字（无描边，逐字绘制以支持字间距）---
    for i, line in enumerate(lines):
        ly = start_y + i * line_height
        line_w = line_widths[i]

        if anchor == "mm":
            cx = anchor_x - line_w // 2
        elif anchor == "rm":
            cx = anchor_x - line_w
        else:
            cx = anchor_x

        # 右对齐覆盖
        if text_align == "right":
            if anchor == "mm":
                cx = anchor_x - line_w // 2
            elif anchor == "lm":
                cx = anchor_x + (max(line_widths) - line_w) if line_widths else cx
            elif anchor == "rm":
                cx = anchor_x - line_w
            else:
                cx = anchor_x - line_w

        x = cx
        for ch in line:
            bbox = draw.textbbox((0, 0), ch, font=font)
            ch_w = bbox[2] - bbox[0]
            draw.text((x, ly), ch, font=font, fill=text_color, anchor="lm")
            x += ch_w + letter_spacing

    return text_layer


def add_brand_watermark(text_layer, draw, img, brand_text, font,
                        position="auto", text_color="#FFFFFF", text_align="center"):
    """添加品牌名水印——复用 resolve_position + draw_text_block，位置/颜色可控。
    默认 auto 上半部居中、纯白色、无阴影面板。
    position 与文案 -p 取值范围一致（"x y" 坐标或 auto）。"""
    if not brand_text:
        return text_layer
    w, h = img.size
    line_height = int(font.size * 1.4)
    text_lines = [brand_text]

    resolved = resolve_position(position)
    if resolved is None:
        # 未指定位置时：回归旧版默认（上半部居中）
        anchor_x, anchor_y = w // 2, int(h * 0.38)
        start_y, t_ax, t_anchor = anchor_y, anchor_x, "mm"
    else:
        anchor_x, anchor_y = resolved
        start_y, t_ax, t_anchor = anchor_y, anchor_x, "lm"

    return draw_text_block(
        text_layer, draw, text_lines, font, t_ax, start_y, line_height,
        anchor=t_anchor, text_color=text_color, solid_block=False, shadow=False,
        text_align=text_align,
    )


def process_image(image_path, text, position=None, font_type="sh1",
                  font_size="auto", color="#FFFFFF", brand=None,
                  letter_spacing=4, text_align="left",
                  brand_position="auto", brand_color="#FFFFFF", brand_size="auto",
                  line_gap=16, padding_x=5, padding_y=5):
    """
    主处理函数：给图片添加文字叠加效果。

    Args:
        image_path: 输入图片路径
        text: 要添加的文案
        position: 文字位置 ('"x y"' 坐标如 "0 0" 左上角，或 None/auto 智能判断)
        font_type: 字体类型 (sh1/sh2/sh3/yahei/kaiti/xingshu)
        font_size: 字体大小 (数字或 "auto")
        color: 文字颜色
        brand: 品牌名称水印
        letter_spacing: 字间距（像素）
        text_align: 文字对齐方式 ("left" 左对齐 / "right" 右对齐 / "center" 居中)，默认 "left"
        brand_position: 品牌名位置（同 position，默认 "auto" 上半部居中）
        brand_color: 品牌名颜色（默认白色）
        brand_size: 品牌名字号（数字或 "auto"，默认 auto=主文字号 1.4 倍）
        line_gap: 多行文案之间的可见行间距（像素），默认 16
        padding_x: 阴影/面板左右内边距（像素），默认 5；调大→左右阴影横向延伸
        padding_y: 阴影/面板上下内边距（像素），默认 5；调大→上下阴影纵向延伸

    Returns:
        输出图片的绝对路径
    """
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)

    # 字体大小自适应
    if font_size == "auto":
        base_size = max(28, min(int(w * 0.048), 80))
    else:
        base_size = int(font_size)

    main_font = load_font(font_type, base_size)

    # 品牌字号：可指定数字，否则默认主文字号的 1.4 倍
    if brand_size == "auto":
        brand_font_size = max(36, int(base_size * 1.4))
    else:
        brand_font_size = int(brand_size)
    brand_font = load_font("kaiti", brand_font_size)

    # 折行处理
    max_text_width = int(w * 0.82)
    text_lines = wrap_text(text, main_font, max_text_width, draw)
    if len(text_lines) == 1 and len(text) <= 12:
        text_lines = [text]

    # 确定位置
    # 阴影盒高度：紧凑包裹文字（约等于字号 × 1.25）
    box_height = int(base_size * 1.25)
    # 行步进高度 = 阴影盒高度 + 上下各 padding + 可见行间距(line_gap)
    line_height = box_height + 2 * 2 + line_gap
    total_text_height = len(text_lines) * line_height

    resolved_pos = resolve_position(position)

    # 品牌名（先画，置于底层）
    if brand:
        text_layer = add_brand_watermark(
            text_layer, draw, img, brand, brand_font,
            position=brand_position, text_color=brand_color, text_align="center",
        )
        draw = ImageDraw.Draw(text_layer)

    if resolved_pos is None:
        # 智能定位：默认底部向上排列，水平按 text_align
        anchor_x, anchor_y = smart_position(img, text_lines, main_font, line_height)
        start_y = anchor_y - total_text_height + line_height // 2
        if text_align == "left":
            t_ax, t_anchor = int(w * 0.06) + int(w * 0.08), "lm"
        elif text_align == "right":
            t_ax, t_anchor = w - int(w * 0.06) - int(w * 0.08), "rm"
        else:
            t_ax, t_anchor = anchor_x, "mm"
    else:
        anchor_x, anchor_y = resolved_pos
        start_y = anchor_y + line_height // 2
        t_ax, t_anchor = anchor_x, "lm"

    # 绘制主文案块（逐行独立阴影 + 无描边纯色文字，每行阴影跟随该行文字宽度）
    text_layer = draw_text_block(
        text_layer, draw, text_lines, main_font, t_ax, start_y, line_height,
        anchor=t_anchor, text_color=color, block_alpha=70,
        shadow_alpha=35, padding_x=padding_x, padding_y=padding_y, radius=12, blur=1, solid_block=False,
        letter_spacing=letter_spacing, text_align=text_align, box_height=box_height,
    )

    # 合成输出
    result = Image.alpha_composite(img, text_layer)
    result_rgb = result.convert("RGB")

    base, ext = os.path.splitext(image_path)
    output_path = f"{base}1{ext}"

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    save_kwargs = {"quality": 95}
    ext_lower = os.path.splitext(output_path)[1].lower()
    if ext_lower in (".png", ".webp"):
        result.save(output_path, **save_kwargs)
    else:
        result_rgb.save(output_path, **save_kwargs)

    return os.path.abspath(output_path)


def main():
    parser = argparse.ArgumentParser(description="图片文案叠加工具 - 医美朋友圈宣传图制作")
    parser.add_argument("--input", "-i", required=True, help="输入图片路径")
    parser.add_argument("--text", "-t", required=True, help="要叠加的文案内容")
    parser.add_argument("--position", "-p", default=None,
                        help='文字位置: "x y" 坐标(如 "0 0" 左上角)，或不指定则智能判断(auto)')
    parser.add_argument("--font", "-f", default="sh1",
                        choices=["sh1", "sh2", "sh3", "yahei", "kaiti", "xingshu"],
                        help="字体: sh1(思源黑体,默认)/sh2(中等)/sh3(粗体)/yahei(微软雅黑)/kaiti(楷体)/xingshu(行书)")
    parser.add_argument("--font-size", "-s", default="auto", help="字体大小 (数字或 auto)")
    parser.add_argument("--color", "-c", default="#FFFFFF", help="文字颜色，默认白色")
    parser.add_argument("--brand", "-b", default=None, help="品牌名称 (如 YIQING)")
    parser.add_argument("--brand-position", "-bp", default="auto",
                        help='品牌名位置: "x y" 坐标(如 "0 0" 左上角)，或 auto 默认上半部居中')
    parser.add_argument("--brand-color", "-bc", default="#FFFFFF", help="品牌名颜色，默认白色")
    parser.add_argument("--brand-size", "-bs", default="auto",
                        help="品牌名字号 (数字或 auto，默认 auto=主文字号 1.4 倍)")
    parser.add_argument("--letter-spacing", "-ls", default=4, type=int,
                        help="字间距 (像素)，默认 4，0 表示无间距")
    parser.add_argument("--line-gap", "-lg", default=18, type=int,
                        help="多行文案之间的可见行间距 (像素)，默认 18")
    parser.add_argument("--padding-x", "-px", default=5, type=int,
                        help="阴影/面板左右内边距 (像素)，默认 5；调大可横向延展左右阴影而不动上下")
    parser.add_argument("--padding-y", "-py", default=5, type=int,
                        help="阴影/面板上下内边距 (像素)，默认 5；调大可纵向延展上下阴影")
    parser.add_argument("--align", "-a", default="left", choices=["left", "right", "center"],
                        help="文字对齐方式: left(左对齐，默认) / right(右对齐) / center(居中)")

    args = parser.parse_args()

    try:
        result_path = process_image(
            image_path=args.input, text=args.text, position=args.position,
            font_type=args.font, font_size=args.font_size, color=args.color,
            brand=args.brand, letter_spacing=args.letter_spacing, text_align=args.align,
            brand_position=args.brand_position, brand_color=args.brand_color,
            brand_size=args.brand_size, line_gap=args.line_gap,
            padding_x=args.padding_x, padding_y=args.padding_y,
        )
        print(json.dumps({"success": True, "output": result_path}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
