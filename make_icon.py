from PIL import Image, ImageDraw, ImageFont

# 创建一个 256x256 的深灰色圆角矩形背景
img = Image.new('RGBA', (256, 256), color=(0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle((10, 10, 246, 246), radius=40, fill=(30, 30, 30, 255), outline=(0, 255, 0, 255), width=8)

# 写入 JDK 字样 (如果没有字体会使用默认字体)
try:
    font = ImageFont.truetype("arialbd.ttf", 100)
except:
    font = ImageFont.load_default()

# 居中绘制绿色文字
draw.text((128, 128), "JDK", fill=(0, 255, 0, 255), font=font, anchor="mm")

# 保存为标准的 ico 图标文件
img.save("logo.ico", format="ICO", sizes=[(256, 256)])
print("✅ 图标 logo.ico 已生成！")