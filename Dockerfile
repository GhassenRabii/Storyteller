FROM public.ecr.aws/lambda/python:3.10

# 1. Install minimal tools
RUN yum install -y curl tar xz && yum clean all

# 2. Download and unpack a static AL2-compatible build
RUN curl -sSL \
    https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
  | tar -xJ \
 && cp ffmpeg-*-static/ffmpeg /usr/local/bin/ \
 && cp ffmpeg-*-static/ffprobe /usr/local/bin/ \
 && rm -rf ffmpeg-*-static*

# 3. Ensure /usr/local/bin is on PATH (it already is in the Lambda base image)
ENV PATH="/usr/local/bin:${PATH}"

WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["app.handler"]
