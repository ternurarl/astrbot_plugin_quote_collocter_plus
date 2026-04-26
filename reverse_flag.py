with open("flag.zip", "rb") as f:
    data = f.read()

with open("flag.bin", "wb") as f:
    f.write(data[::-1])
