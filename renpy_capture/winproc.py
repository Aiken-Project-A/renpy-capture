"""Windows: the engine runs in a Job Object that kills it, and anything it starts, when the capture stops it or dies;
and the places its window can be kept: the user's desktop, beyond the edge of the screen, or a desktop of its own.

Nothing here is imported on other systems."""
import ctypes
import os
import subprocess
import threading
from ctypes import wintypes

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
u32 = ctypes.WinDLL('user32', use_last_error=True)

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
GENERIC_ALL = 0x10000000
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
FAR = -20000                                        # where a window off the screen goes (minimised ones sit at -32000)


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                                                   'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION), ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR),
                ('lpTitle', wintypes.LPWSTR), ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
                ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD), ('dwXCountChars', wintypes.DWORD),
                ('dwYCountChars', wintypes.DWORD), ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD), ('lpReserved2', ctypes.c_void_p),
                ('hStdInput', wintypes.HANDLE), ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [('StartupInfo', STARTUPINFOW), ('lpAttributeList', ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE), ('dwProcessId', wintypes.DWORD),
                ('dwThreadId', wintypes.DWORD)]


def _proto(fn, res, *args):
    fn.restype, fn.argtypes = res, list(args)


_proto(k32.CreateJobObjectW, wintypes.HANDLE, ctypes.c_void_p, wintypes.LPCWSTR)
_proto(k32.SetInformationJobObject, wintypes.BOOL, wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
_proto(k32.AssignProcessToJobObject, wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE)
_proto(k32.TerminateJobObject, wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
_proto(k32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
_proto(k32.WaitForSingleObject, wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
_proto(k32.GetExitCodeProcess, wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
_proto(k32.InitializeProcThreadAttributeList, wintypes.BOOL, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
       ctypes.POINTER(ctypes.c_size_t))
_proto(k32.UpdateProcThreadAttribute, wintypes.BOOL, ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t,
       ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p)
_proto(k32.DeleteProcThreadAttributeList, None, ctypes.c_void_p)
_proto(k32.CreateProcessW, wintypes.BOOL, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
       wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOEXW),
       ctypes.POINTER(PROCESS_INFORMATION))
_proto(u32.CreateDesktopW, wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
       wintypes.DWORD, ctypes.c_void_p)
_proto(u32.CloseDesktop, wintypes.BOOL, wintypes.HANDLE)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_proto(u32.EnumWindows, wintypes.BOOL, WNDENUMPROC, wintypes.LPARAM)
_proto(u32.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_proto(u32.IsWindowVisible, wintypes.BOOL, wintypes.HWND)
_proto(u32.GetWindowRect, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_proto(u32.SetWindowPos, wintypes.BOOL, wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
       ctypes.c_int, wintypes.UINT)


def _check(ok, what):
    if not ok:
        raise OSError(f'{what}: {ctypes.FormatError(ctypes.get_last_error())}')
    return ok


class Job:
    """A Job Object that kills every process in it when it is killed or when its last handle closes: ours is never
    inherited, so it closes when the capture ends, however it ends (Ctrl+C, a closed console, the task manager)."""

    def __init__(self):
        self.h = _check(k32.CreateJobObjectW(None, None), 'CreateJobObject')
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        _check(k32.SetInformationJobObject(self.h, JobObjectExtendedLimitInformation, ctypes.byref(info),
                                           ctypes.sizeof(info)), 'SetInformationJobObject')

    def add(self, handle):
        """Processes the one added starts from now on are in the job too."""
        _check(k32.AssignProcessToJobObject(self.h, handle), 'AssignProcessToJobObject')

    def kill(self):
        if self.h:
            k32.TerminateJobObject(self.h, 1)

    def close(self):
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None


class Process:
    """A process started by CreateProcessW, with what the run loop asks of a subprocess.Popen."""

    def __init__(self, handle, pid, args):
        self._handle, self.pid, self.args, self.returncode = handle, pid, args, None

    def poll(self):
        if self.returncode is None and k32.WaitForSingleObject(self._handle, 0) == 0:
            code = wintypes.DWORD()
            k32.GetExitCodeProcess(self._handle, ctypes.byref(code))
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        ms = INFINITE if timeout is None else int(timeout * 1000)
        if self.returncode is None and k32.WaitForSingleObject(self._handle, ms) == WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.poll()

    def __del__(self):
        if getattr(self, '_handle', None):
            k32.CloseHandle(self._handle)
            self._handle = None


def _env_block(env):
    """An environment for CreateProcessW: k=v\\0…\\0, sorted without regard to case, as Windows wants it."""
    return ''.join(f'{k}={v}\0' for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + '\0'


def _create_on_desktop(cmd, env, out, desktop):
    """CreateProcessW on the desktop ``desktop`` (subprocess cannot name one), its output into the open file ``out``.
    Only its own standard handles are inherited (a handle list), so engines started at once by several workers do not
    keep each other's files open."""
    import _winapi
    import msvcrt
    me = _winapi.GetCurrentProcess()

    def inheritable(h):
        return _winapi.DuplicateHandle(me, h, me, 0, True, _winapi.DUPLICATE_SAME_ACCESS)

    with open(os.devnull, 'rb') as null:
        hin, hout = inheritable(msvcrt.get_osfhandle(null.fileno())), inheritable(msvcrt.get_osfhandle(out.fileno()))
    try:
        size = ctypes.c_size_t()
        k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attrs = ctypes.create_string_buffer(size.value)
        _check(k32.InitializeProcThreadAttributeList(attrs, 1, 0, ctypes.byref(size)),
               'InitializeProcThreadAttributeList')
        handles = (wintypes.HANDLE * 2)(hin, hout)
        try:
            _check(k32.UpdateProcThreadAttribute(attrs, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handles,
                                                 ctypes.sizeof(handles), None, None), 'UpdateProcThreadAttribute')
            si = STARTUPINFOEXW()
            si.StartupInfo.cb = ctypes.sizeof(si)
            si.StartupInfo.lpDesktop = desktop
            si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = hin, hout, hout
            si.lpAttributeList = ctypes.cast(attrs, ctypes.c_void_p)
            pi = PROCESS_INFORMATION()
            line = ctypes.create_unicode_buffer(subprocess.list2cmdline(cmd))
            block = ctypes.create_unicode_buffer(_env_block(env))
            flags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT \
                | EXTENDED_STARTUPINFO_PRESENT
            _check(k32.CreateProcessW(None, line, None, None, True, flags, block, None, ctypes.byref(si),
                                      ctypes.byref(pi)), f'CreateProcess {cmd[0]}')
        finally:
            k32.DeleteProcThreadAttributeList(attrs)
    finally:
        _winapi.CloseHandle(hin)
        _winapi.CloseHandle(hout)
    k32.CloseHandle(pi.hThread)
    return Process(pi.hProcess, pi.dwProcessId, cmd)


def start(cmd, env, out, job, desktop=None):
    """Start ``cmd`` under ``env`` (the whole environment) with its output into the open file ``out``, in ``job``, on
    the desktop named ``desktop`` (None: the user's). A new process group and no console: Ctrl+C in the user's
    console reaches the capture, which then kills the job, never the engine half-way through a write."""
    if desktop is None:
        p = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
    else:
        p = _create_on_desktop(cmd, env, out, desktop)
    try:
        job.add(int(p._handle))                     # long before the engine is far enough to start anything itself
    except OSError:
        import _winapi
        _winapi.TerminateProcess(int(p._handle), 1)
        raise
    return p


class Desktop:
    """A desktop of its own in the user's window station: windows on it are never shown on the user's screen, and
    the user's mouse and keyboard never reach them."""

    def __init__(self, name):
        self.name = name
        self.h = _check(u32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None), f'CreateDesktop {name}')

    def close(self):
        if self.h:
            u32.CloseDesktop(self.h)
            self.h = None


def windows_of(pid):
    """The visible top-level windows of a process (on the desktop of the caller)."""
    found = []

    def each(hwnd, _):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    u32.EnumWindows(WNDENUMPROC(each), 0)
    return found


class Mover(threading.Thread):
    """Keeps the windows of a process beyond the left and top edges of the screen, where they are still drawn but
    not seen: looks a few times a second, since the engine centres its window once it has a size."""

    def __init__(self, pid):
        super().__init__(daemon=True)
        self.pid, self.done, self.moved = pid, threading.Event(), 0

    def run(self):
        while not self.done.wait(0.05 if not self.moved else 0.25):
            for hwnd in windows_of(self.pid):
                r = wintypes.RECT()
                if u32.GetWindowRect(hwnd, ctypes.byref(r)) and r.left > FAR // 2:
                    u32.SetWindowPos(hwnd, None, FAR, FAR, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                    self.moved += 1

    def stop(self):
        self.done.set()
