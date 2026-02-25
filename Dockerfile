FROM apache/airflow:2.10.4-python3.12

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Copy source modules so they're available to DAGs
COPY src/ /opt/airflow/src/
