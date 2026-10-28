# centinela-smart-tests: Playwright + Chromium (the container IS the browser sandbox) + the shared library.
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
RUN pip install --no-cache-dir "playwright==1.49.0" "openpyxl==3.1.5" "hvac==2.3.0" "requests==2.32.3" "axe-playwright-python==0.1.8"
COPY libs/centinela-core /opt/centinela-core
RUN pip install --no-cache-dir /opt/centinela-core
WORKDIR /app
COPY smart_tests /app/smart_tests
USER pwuser
ENTRYPOINT ["python", "-m", "smart_tests"]
