FROM kylin-base-torch:v1.0.0

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

EXPOSE 8080

CMD ["python3", "equipment_interface.py"]
