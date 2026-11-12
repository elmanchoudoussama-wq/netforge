"""
gpucore
-------
Neutral wrapper for running vectorized numeric kernels on any OpenCL GPU.

Nothing here knows about any particular algorithm. It just:
1. enumerates devices
2. compiles a .cl source string
3. uploads flat byte arrays / int arrays as arguments
4. dispatches a 1-D NDRange
5. reads back results
"""
import ctypes
from ._cl_loader import (
    load_opencl_library, _bind, CL_SUCCESS,
    CL_PLATFORM_NAME, CL_DEVICE_NAME, CL_DEVICE_TYPE_ALL,
    CL_MEM_READ_ONLY, CL_MEM_WRITE_ONLY, CL_MEM_COPY_HOST_PTR,
    cl_platform_id, cl_device_id, cl_context, cl_command_queue,
    cl_program, cl_kernel, cl_mem, cl_int, cl_uint, size_t,
)


class GPUError(RuntimeError):
    pass


def _check(err, what="OpenCL call"):
    if err != CL_SUCCESS:
        raise GPUError(f"{what} failed (code {err})")


class VectorKernel:
    """A compiled OpenCL kernel bound to a DeviceContext."""

    def __init__(self, ctx, program, kernel_name):
        self._ctx = ctx
        self._lib = ctx.lib
        self._fns = ctx.fns
        self._program = program
        self._kernel = self._fns["clCreateKernel"](
            program, kernel_name.encode(), ctypes.byref(cl_int())
        )
        if not self._kernel:
            raise GPUError(f"Could not create kernel '{kernel_name}'")

    def set_arg_buffer(self, index, buf):
        # clCreateBuffer may return a plain int (pointer) or a c_void_p
        ptr = buf.value if hasattr(buf, "value") else int(buf)
        arg = ctypes.c_void_p(ptr)
        err = self._fns["clSetKernelArg"](
            self._kernel, index, ctypes.sizeof(cl_mem),
            ctypes.byref(arg)
        )
        _check(err, "clSetKernelArg(buffer)")

    def set_arg_scalar(self, index, value, typecode):
        """typecode: 'i' for int32, 'I' for uint32, 'Q' for uint64."""
        if typecode == 'i':
            v = ctypes.c_int32(int(value))
        elif typecode == 'I':
            v = ctypes.c_uint32(int(value))
        elif typecode == 'Q':
            v = ctypes.c_uint64(int(value))
        else:
            raise ValueError(typecode)
        err = self._fns["clSetKernelArg"](
            self._kernel, index, ctypes.sizeof(v), ctypes.byref(v)
        )
        _check(err, "clSetKernelArg(scalar)")

    def dispatch(self, global_size):
        gsz = (size_t * 1)(global_size)
        err = self._fns["clEnqueueNDRangeKernel"](
            self._ctx.queue, self._kernel, 1,
            None, gsz, None, 0, None, None
        )
        _check(err, "clEnqueueNDRangeKernel")
        self._fns["clFinish"](self._ctx.queue)

    def release(self):
        if self._kernel:
            self._fns["clReleaseKernel"](self._kernel)
            self._kernel = None


class DeviceContext:
    def __init__(self, device_index=0):
        self.lib = load_opencl_library()
        self.fns = _bind(self.lib)

        # enumerate platforms
        n_plat = cl_uint(0)
        _check(self.fns["clGetPlatformIDs"](0, None, ctypes.byref(n_plat)),
               "clGetPlatformIDs")
        if n_plat.value == 0:
            raise GPUError("No OpenCL platforms found on this system.")

        platforms = (cl_platform_id * n_plat.value)()
        _check(self.fns["clGetPlatformIDs"](n_plat.value, platforms,
                                            ctypes.byref(n_plat)),
               "clGetPlatformIDs(2)")

        self.all_devices = []
        for pid in platforms:
            n_dev = cl_uint(0)
            err = self.fns["clGetDeviceIDs"](pid, CL_DEVICE_TYPE_ALL,
                                             0, None, ctypes.byref(n_dev))
            if err != CL_SUCCESS or n_dev.value == 0:
                continue
            devs = (cl_device_id * n_dev.value)()
            self.fns["clGetDeviceIDs"](pid, CL_DEVICE_TYPE_ALL,
                                       n_dev.value, devs, ctypes.byref(n_dev))
            pname = self._query_info(self.fns["clGetPlatformInfo"],
                                     pid, CL_PLATFORM_NAME)
            for d in devs:
                dname = self._query_info(self.fns["clGetDeviceInfo"],
                                         d, CL_DEVICE_NAME)
                self.all_devices.append({
                    "platform": pname,
                    "name": dname,
                    "device_id": d,
                })

        if not self.all_devices:
            raise GPUError("No OpenCL devices available.")

        if not (0 <= device_index < len(self.all_devices)):
            raise GPUError(f"device_index {device_index} out of range "
                           f"(have {len(self.all_devices)})")

        chosen = self.all_devices[device_index]
        self.device_id = chosen["device_id"]
        self.device_name = chosen["name"]
        self.platform_name = chosen["platform"]

        err = cl_int(0)
        self.context = self.fns["clCreateContext"](
            None, 1, ctypes.byref(ctypes.c_void_p(self.device_id)),
            None, None, ctypes.byref(err)
        )
        _check(err.value, "clCreateContext")

        self.queue = self.fns["clCreateCommandQueue"](
            self.context, self.device_id, 0, ctypes.byref(err)
        )
        _check(err.value, "clCreateCommandQueue")

    @staticmethod
    def _query_info(fn, obj, param, size_hint=512):
        buf = ctypes.create_string_buffer(size_hint)
        ret = size_t(0)
        fn(obj, param, size_hint, buf, ctypes.byref(ret))
        return buf.value.decode("utf-8", errors="replace").strip("\x00")

    def compile(self, source: str, kernel_name: str) -> VectorKernel:
        src_bytes = source.encode("utf-8")
        src_ptr = ctypes.c_char_p(src_bytes)
        length = size_t(len(src_bytes))
        err = cl_int(0)
        prog = self.fns["clCreateProgramWithSource"](
            self.context, 1, ctypes.byref(src_ptr), ctypes.byref(length),
            ctypes.byref(err)
        )
        _check(err.value, "clCreateProgramWithSource")

        build_err = self.fns["clBuildProgram"](
            prog, 1, ctypes.byref(ctypes.c_void_p(self.device_id)),
            b"", None, None
        )
        if build_err != CL_SUCCESS:
            # fetch build log
            log_size = size_t(0)
            self.fns["clGetProgramBuildInfo"](
                prog, self.device_id, 0x1183, 0, None, ctypes.byref(log_size)
            )
            log_buf = ctypes.create_string_buffer(log_size.value or 1)
            self.fns["clGetProgramBuildInfo"](
                prog, self.device_id, 0x1183, log_size.value, log_buf,
                ctypes.byref(log_size)
            )
            raise GPUError("Kernel build failed:\n" +
                           log_buf.value.decode("utf-8", errors="replace"))

        return VectorKernel(self, prog, kernel_name)

    def make_buffer(self, data_bytes: bytes, read_only=True):
        flags = CL_MEM_READ_ONLY | CL_MEM_COPY_HOST_PTR if read_only \
                else CL_MEM_WRITE_ONLY
        buf = ctypes.create_string_buffer(data_bytes, len(data_bytes))
        err = cl_int(0)
        handle = self.fns["clCreateBuffer"](
            self.context, flags, len(data_bytes),
            ctypes.cast(buf, ctypes.c_void_p), ctypes.byref(err)
        )
        _check(err.value, "clCreateBuffer")
        return handle

    def make_empty_buffer(self, nbytes):
        err = cl_int(0)
        handle = self.fns["clCreateBuffer"](
            self.context, CL_MEM_WRITE_ONLY, nbytes, None, ctypes.byref(err)
        )
        _check(err.value, "clCreateBuffer(out)")
        return handle

    def read_buffer(self, buf, nbytes):
        out = ctypes.create_string_buffer(nbytes)
        err = self.fns["clEnqueueReadBuffer"](
            self.queue, buf, 1, 0, nbytes,
            ctypes.cast(out, ctypes.c_void_p), 0, None, None
        )
        _check(err, "clEnqueueReadBuffer")
        self.fns["clFinish"](self.queue)
        return out.raw

    def release_buffer(self, buf):
        self.fns["clReleaseMemObject"](buf)
