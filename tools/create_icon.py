#!/usr/bin/env python3
"""
创建 Arena of Valor 主题图标的脚本
将 Arena of Valor logo 转换为 .ico 格式
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_aov_icon():
    """创建 Arena of Valor 主题的图标"""
    
    # 创建 256x256 的图像（推荐尺寸）
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 绘制背景圆形
    margin = 20
    circle_size = size - 2 * margin
    circle_center = size // 2
    circle_bbox = [
        circle_center - circle_size // 2,
        circle_center - circle_size // 2,
        circle_center + circle_size // 2,
        circle_center + circle_size // 2
    ]
    
    # 绘制外圈（金色）
    draw.ellipse(circle_bbox, fill=(255, 215, 0, 255), outline=(218, 165, 32, 255), width=8)
    
    # 绘制内圈（深蓝色）
    inner_margin = 40
    inner_circle_size = circle_size - 2 * inner_margin
    inner_circle_bbox = [
        circle_center - inner_circle_size // 2,
        circle_center - inner_circle_size // 2,
        circle_center + inner_circle_size // 2,
        circle_center + inner_circle_size // 2
    ]
    draw.ellipse(inner_circle_bbox, fill=(25, 25, 112, 255))
    
    # 绘制中心字母 "A"（代表 Arena）
    try:
        # 尝试使用系统字体
        font_size = inner_circle_size // 3
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        # 如果找不到字体，使用默认字体
        font = ImageFont.load_default()
    
    # 绘制白色字母 "A"
    text = "A"
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    text_x = circle_center - text_width // 2
    text_y = circle_center - text_height // 2
    
    draw.text((text_x, text_y), text, fill=(255, 255, 255, 255), font=font)
    
    # 保存为 ICO 文件
    icon_path = "icon.ico"
    
    # 创建多个尺寸的图标
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon_images = []
    
    for s in sizes:
        resized_img = img.resize(s, Image.Resampling.LANCZOS)
        icon_images.append(resized_img)
    
    # 保存为 ICO 文件
    icon_images[0].save(icon_path, format='ICO', sizes=[(s[0], s[1]) for s in sizes])
    
    print(f"图标已创建: {icon_path}")
    print("图标尺寸:", sizes)
    
    return icon_path

if __name__ == "__main__":
    try:
        icon_path = create_aov_icon()
        print(f"✅ 成功创建 Arena of Valor 主题图标: {icon_path}")
        print("现在可以重新打包 exe 文件，它将使用这个图标")
    except Exception as e:
        print(f"❌ 创建图标失败: {e}")
        print("请确保已安装 Pillow 库: pip install Pillow")

