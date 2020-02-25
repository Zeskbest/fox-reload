import shutil
from contextlib import contextmanager

# TODO normal imports
from enum import Enum, auto
from time import sleep
from typing import Iterable

from datetime import datetime

try:
    import git
except ImportError:
    import os

    os.environ["GIT_PYTHON_GIT_EXECUTABLE"] = r"D:\Program Files\Git\bin\git.exe"
    import git

import gitlab
from git import Repo
from gitlab.v4.objects import Project, ProjectPipeline, MergeRequest

from config import CONFIG

PROJECT_NAMES = []
PROJECT_BRANCHES = []
DIR_FOR_STORING_PROJECTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp")
COMMIT_AND_BRANCH_TEMPLATE = "autoupdate_{time}_{submodule}"


def check_credentials():
    Context()
    for project_name in PROJECT_NAMES:
        CONFIG.config_parser.get("ci_trigger_tokens", project_name)


class Context:
    @staticmethod
    def _create_gitlab_client():
        gl = gitlab.Gitlab.from_config('our_gitlab', [CONFIG.filepath])
        gl.auth()
        return gl

    def __init__(self):
        # TODO split into gitlab context
        # TODO split into git context
        # TODO init this object for each project_name
        self.glContext = self._create_gitlab_client()

    def get_project(self, name: str) -> Project:
        luna = self.glContext.groups.get("luna", lazy=True)  # data not needed

        # todo search using gitlab instead python
        projects = luna.projects.list(all=True)
        needed_project = next((p for p in projects if p.attributes["name"] == name))

        return needed_project

    def clone_project(self, project: Project, branch: str) -> git.Repo:
        url = project.ssh_url_to_repo
        project_name = project.attributes["name"]
        repo = git.Repo.clone_from(url, to_path=os.path.join(DIR_FOR_STORING_PROJECTS, project_name), branch=branch)
        repo.submodule_update()
        assert not repo.bare
        return repo

    def try_update_one_submodule(self, submodule, default_branch):
        submodule_repo: git.Repo = submodule.module
        old_sha = submodule_repo.head.object.binsha
        submodule_repo.git.checkout(default_branch)
        submodule_repo.git.pull()
        new_sha = submodule_repo.head.object.binsha
        return old_sha != new_sha

    def get_not_last_submodules_updated(self, repo: git.Repo, default_branch: str) -> Iterable[git.Submodule]:
        for submodule in repo.submodules:
            # submodule.update(init=True) # TODO check if done in self.clone_project
            updated = self.try_update_one_submodule(submodule, default_branch)
            if updated:
                yield submodule

    def create_custom_branch_and_commit_submodule(self, repo: git.Repo, submodule: git.Submodule) -> str:
        branch_name = COMMIT_AND_BRANCH_TEMPLATE.format(
            time=datetime.now().strftime("%y_%m_%d_%H_%M_%S"),
            submodule=submodule.path.replace(os.sep, '.'))
        repo.git.checkout(b=branch_name)
        repo.git.add(submodule.path)
        repo.git.commit(message=branch_name)
        return branch_name

    def push_new_branch(self, repo: git.Repo, branch_name: str):
        assert len(repo.remotes) == 1
        remote: git.Remote = repo.remote()
        repo.git.push(remote_ref_path=f"{remote.name}/{branch_name}")

    def remove_remote_branch(self, repo: git.Repo, branch_name: str):
        remote: git.Remote = repo.remote()
        repo.git.push(delete=True, remote_ref_path=f"{remote.name}/{branch_name}")

    def create_merge_and_wait_pipeline(self, project: Project, branch_name: str, target_branch: str) -> bool:
        mr: MergeRequest = project.mergerequests.create({'source_branch': branch_name,
                                                         'target_branch': target_branch,
                                                         'title': branch_name.replace('_', ' ', ),
                                                         'labels': ['t.efimushkin.auto']})
        pipeline: ProjectPipeline = mr.pipelines()[-1]
        pipeline_result = self.wait_pipeline(pipeline)
        if pipeline_result:
            mr.merge()
        else:
            mr.delete()
        return pipeline_result

    def wait_pipeline(self, pipeline) -> bool:
        TOTAL_TIME = 60 * 60

        class State(Enum):
            running = auto()
            pending = auto()
            success = auto()
            failed = auto()
            canceled = auto()
            skipped = auto()

        for _ in range(60):
            step = 1 / 60
            sleep(TOTAL_TIME / step)
            state: State = State[pipeline.attributes.status]
            if state in (State.running, State.pending):
                continue
            elif state == State.success:
                pipeline_result = True
                break
            else:
                pipeline_result = False
                if state in (State.failed, State.canceled):
                    pass
                else:
                    print(f"SOME SHIT HAPPEN: state {state}")
                break
        else:
            print(f"Cannot reach required condition in {TOTAL_TIME} seconds.")
            pipeline_result = False

        return pipeline_result

    def shutdown_project(self, repo: git.Repo):
        shutil.rmtree(repo.working_dir)
        shutil.rmtree(repo.working_tree_dir)
        repo.close()
        # todo remove custom branch
        # todo checkout default branch
        # todo update submodules with force flag
        # todo assert git status == clear
        pass

    # @contextmanager
    # def project_context(self):
    #     # todo create
    #     yield
    #     # todo stop
    #     pass

    def pipeline(self):
        project_name = PROJECT_NAMES[0]
        default_branch = PROJECT_BRANCHES[0]
        proj = self.get_project(project_name)

        repo = self.clone_project(proj, branch=default_branch)
        submodule = next(self.get_not_last_submodules_updated(repo, default_branch=default_branch), None)
        if submodule is None:
            print(f"Project '{project_name}' already up to date.")
            return
        custom_branch: str = self.create_custom_branch_and_commit_submodule(repo, submodule)
        self.push_new_branch(repo, custom_branch)

        success = self.create_merge_and_wait_pipeline(proj, custom_branch, default_branch)
        print(success)
        self.remove_remote_branch(repo, custom_branch)
        self.shutdown_project(repo)


if __name__ == '__main__':
    check_credentials()
    Context().pipeline()
