"""Windows Job Object 管理本次进程树；不按名称或端口杀其他进程。"""

import os
import subprocess
import time
from .interrupts import uninterrupted_cleanup


class ProcessTree:
    """挂起创建 → 加入 Job → 恢复，避免启动器先派生出未受管的子进程。"""

    def __init__(self, command, *, env, output):
        # 句柄登记和加入 Job 必须原子完成，避免 Ctrl+C 留下尚未受管的挂起进程。
        with uninterrupted_cleanup():
            self._start(command, env=env, output=output)

    def _start(self, command, *, env, output):
        if os.name != 'nt':
            raise RuntimeError('抓包进程树管理只支持 Windows')
        import msvcrt
        import win32api
        import win32con
        import win32job
        import win32process

        self.handle = None
        self.job = None
        self.returncode = None
        self.pid = None
        self.assigned = False
        duplicates = []
        thread = None
        try:
            self.job = win32job.CreateJobObject(None, '')
            info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
            info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)

            def inheritable(stream):
                handle = win32api.DuplicateHandle(win32api.GetCurrentProcess(), msvcrt.get_osfhandle(stream.fileno()),
                                                 win32api.GetCurrentProcess(), 0, True, win32con.DUPLICATE_SAME_ACCESS)
                duplicates.append(handle)
                return handle

            with open(os.devnull, 'rb') as stdin:
                startup = win32process.STARTUPINFO()
                startup.dwFlags = win32con.STARTF_USESTDHANDLES
                startup.hStdInput = inheritable(stdin)
                startup.hStdOutput = inheritable(output)
                startup.hStdError = startup.hStdOutput
                self.handle, thread, self.pid, _ = win32process.CreateProcess(
                    None, subprocess.list2cmdline(command), None, None, True,
                    win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW, env, None, startup)
            try:
                win32job.AssignProcessToJobObject(self.job, self.handle)
                self.assigned = True
            except BaseException:
                # 分配失败时尚未执行启动器，直接终止自己创建的挂起进程。
                win32api.TerminateProcess(self.handle, 1)
                raise
            win32process.ResumeThread(thread)
        except BaseException:
            self.close()
            raise
        finally:
            if thread is not None:
                thread.Close()
            for duplicate in duplicates:
                duplicate.Close()

    def poll(self):
        if self.handle is None:
            return self.returncode
        import win32event
        import win32process
        if win32event.WaitForSingleObject(self.handle, 0) == win32event.WAIT_OBJECT_0:
            self.returncode = win32process.GetExitCodeProcess(self.handle)
        return self.returncode

    def close(self):
        """即使启动器已退出，也终止 Job 内尚存的子进程。可重复调用。"""
        import win32job
        import win32event
        import win32api
        try:
            if self.handle is not None and not self.assigned and self.poll() is None:
                win32api.TerminateProcess(self.handle, 1)
            if self.job is not None:
                win32job.TerminateJobObject(self.job, 1)
                deadline = time.monotonic() + 5
                while win32job.QueryInformationJobObject(self.job, win32job.JobObjectBasicAccountingInformation)['ActiveProcesses']:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('mitmproxy 进程树未在 5 秒内退出')
                    time.sleep(0.05)
            if self.handle is not None:
                win32event.WaitForSingleObject(self.handle, 5000)
                self.poll()
        finally:
            if self.job is not None:
                self.job.Close()
                self.job = None
            if self.handle is not None:
                self.handle.Close()
                self.handle = None
