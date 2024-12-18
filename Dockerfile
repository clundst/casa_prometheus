FROM conda/miniconda3
WORKDIR /app
COPY environment.yml .
RUN conda config --add channels conda-forge
#RUN conda create -n htcondor --file=environment.yml
RUN conda install -c conda-forge htcondor prometheus_client

#SHELL ["conda","run","-n", "htcondor", "/bin/bash", "-c"]
COPY . .
EXPOSE 9090
#CMD ["conda", "run","-n","htcondor","python","condor_usage_metrics.py"]
CMD ["python","condor_usage_metrics.py"]
