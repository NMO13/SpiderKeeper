import datetime, time

import requests

from SpiderKeeper.app.proxy.spiderctrl import SpiderServiceProxy
from SpiderKeeper.app.spider.model import SpiderStatus, Project, SpiderInstance
from SpiderKeeper.app.util.http import request


class ScrapydProxy(SpiderServiceProxy):
    def __init__(self, server):
        self.spider_status_name_dict = {
            SpiderStatus.PENDING: 'pending',
            SpiderStatus.RUNNING: 'running',
            SpiderStatus.FINISHED: 'finished'
        }
        super(ScrapydProxy, self).__init__(server)

    def _scrapyd_url(self):
        return self.server

    def get_project_list(self):
        data = request("get", self._scrapyd_url() + "/listprojects.json", return_type="json")
        result = []
        if data:
            for project_name in data['projects']:
                project = Project()
                project.project_name = project_name
                result.append(project)
        return result

    def delete_project(self, project_name):
        post_data = dict(project=project_name)
        data = request("post", self._scrapyd_url() + "/delproject.json", data=post_data, return_type="json")
        return True if data and data['status'] == 'ok' else False

    def get_spider_list(self, project_name):
        data = request("get", self._scrapyd_url() + "/listspiders.json?project=%s" % project_name,
                       return_type="json")
        result = []
        if data and data['status'] == 'ok':
            for spider_name in data['spiders']:
                spider_instance = SpiderInstance()
                spider_instance.spider_name = spider_name
                result.append(spider_instance)
        return result

    def get_daemon_status(self):
        pass

    def get_job_list(self, project_name, project_id, spider_status=None):
        data = request("get", self._scrapyd_url() + "/listjobs.json?project=%s" % project_name,
                       return_type="json")
        result = {SpiderStatus.PENDING: [], SpiderStatus.RUNNING: [], SpiderStatus.FINISHED: []}
        if data and data['status'] == 'ok':
            for _status in self.spider_status_name_dict.keys():
                for item in data[self.spider_status_name_dict[_status]]:
                    # create a new job execution for newly discovered spiders
                    self.create_job_execution(item, project_id)
                    start_time, end_time = None, None
                    if item.get('start_time'):
                        start_time = datetime.datetime.strptime(item['start_time'], '%Y-%m-%d %H:%M:%S.%f')
                    if item.get('end_time'):
                        end_time = datetime.datetime.strptime(item['end_time'], '%Y-%m-%d %H:%M:%S.%f')
                    result[_status].append(dict(id=item['id'], start_time=start_time, end_time=end_time))
        return result if not spider_status else result[spider_status]

    def create_job_execution(self, job, project_id):
        from SpiderKeeper.app.spider.model import JobExecution, JobInstance, JobRunType
        from SpiderKeeper.app import agent
        from SpiderKeeper.app import db

        execution_id = job.get('id', 0)

        if JobExecution.query.filter_by(service_job_execution_id = execution_id).first():
            return

        job_instance = JobInstance()
        job_instance.spider_name = job.get('spider', 'unknown')
        job_instance.project_id = project_id
        job_instance.spider_arguments = ''
        job_instance.priority = 0
        job_instance.run_type = JobRunType.ONETIME
        db.session.add(job_instance)
        db.session.commit()

        job_execution = JobExecution()
        job_execution.project_id = project_id
        job_execution.service_job_execution_id = execution_id
        job_execution.job_instance_id = 0
        job_execution.create_time = self.convert_time(job, 'start_time')
        job_execution.end_time = self.convert_time(job, 'end_time')
        job_execution.running_on = agent.spider_service_instances[0].server
        job_execution.job_instance = job_instance
        job_execution.job_instance_id = job_instance.id
        db.session.add(job_execution)
        db.session.commit()

    def convert_time(self, job, position):
        date = job.get(position, None)
        if date:
            res = datetime.datetime.strptime(date.split()[0], '%Y-%m-%d')
        else:
            res = datetime.datetime.now()
        return res

    def start_spider(self, project_name, spider_name, arguments):
        post_data = dict(project=project_name, spider=spider_name)
        post_data.update(arguments)
        data = request("post", self._scrapyd_url() + "/schedule.json", data=post_data, return_type="json")
        return data['jobid'] if data and data['status'] == 'ok' else None

    def cancel_spider(self, project_name, job_id):
        post_data = dict(project=project_name, job=job_id)
        data = request("post", self._scrapyd_url() + "/cancel.json", data=post_data, return_type="json")
        return data != None

    def deploy(self, project_name, file_path):
        with open(file_path, 'rb') as f:
            eggdata = f.read()
        res = requests.post(self._scrapyd_url() + '/addversion.json', data={
            'project': project_name,
            'version': int(time.time()),
            'egg': eggdata,
        })
        return res.text if res.status_code == 200 else None

    def get_log_url(self, project_name, spider_name, job_id):
        return self._scrapyd_url() + '/logs/%s/%s/%s.log' % (project_name, spider_name, job_id)
