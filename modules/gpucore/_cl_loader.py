"""
gpucore._cl_loader
-------------------
Minimal ctypes bridge to the OpenCL ICD loader.

We do NOT use pyopencl or any third-party GPU library. We link directly
against the OS-provided OpenCL shared library (libOpenCL.so / OpenCL.dll),
which is the same library every OpenCL program uses.
"""
import ctypes
import ctypes.util
import os
import sys
import platform

_CL_LIB = None


def load_opencl_library():
    """Locate & load the system OpenCL ICD loader."""
    global _CL_LIB
    if _CL_LIB is not None:
        return _CL_LIB

    candidates = []
    sysname = platform.system()

    if sysname == "Linux":
        candidates = ["libOpenCL.so.1", "libOpenCL.so"]
    elif sysname == "Darwin":
        candidates = [
            "/System/Library/Frameworks/OpenCL.framework/OpenCL",
            "libOpenCL.dylib",
        ]
    elif sysname == "Windows":
        candidates = ["OpenCL.dll"]
    else:
        raise OSError(f"Unsupported platform: {sysname}")

    last_err = None
    for name in candidates:
        try:
            _CL_LIB = ctypes.CDLL(name)
            return _CL_LIB
        except OSError as e:
            last_err = e

    found = ctypes.util.find_library("OpenCL")
    if found:
        _CL_LIB = ctypes.CDLL(found)
        return _CL_LIB

    raise OSError(
        "Could not load OpenCL runtime. Install a GPU driver with OpenCL "
        "support (NVIDIA/AMD/Intel all ship one). Last error: "
        f"{last_err}"
    )


# --- Minimal OpenCL type/marshalling definitions ---------------------------
# We only declare the ~15 functions needed to build a kernel and dispatch it.

cl_int = ctypes.c_int32
cl_uint = ctypes.c_uint32
cl_ulong = ctypes.c_uint64
cl_device_type = ctypes.c_uint64
cl_platform_id = ctypes.c_void_p
cl_device_id = ctypes.c_void_p
cl_context = ctypes.c_void_p
cl_command_queue = ctypes.c_void_p
cl_program = ctypes.c_void_p
cl_kernel = ctypes.c_void_p
cl_mem = ctypes.c_void_p
cl_event = ctypes.c_void_p
size_t = ctypes.c_size_t
void_p = ctypes.c_void_p

CL_SUCCESS = 0

CL_PLATFORM_NAME = 0x0902
CL_DEVICE_NAME = 0x102B
CL_DEVICE_TYPE_ALL = 0xFFFFFFFF

CL_MEM_READ_ONLY = 1 << 2
CL_MEM_WRITE_ONLY = 1 << 1
CL_MEM_READ_WRITE = 1 << 0
CL_MEM_COPY_HOST_PTR = 1 << 5

CL_TRUE = 1
CL_FALSE = 0


def _bind(lib):
    """Declare argtypes/restype for each function we use."""
    def bind(name, restype, *argtypes):
        fn = getattr(lib, name)
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    return {
        "clGetPlatformIDs": bind("clGetPlatformIDs",
            cl_int, cl_uint, ctypes.POINTER(cl_platform_id),
            ctypes.POINTER(cl_uint)),
        "clGetDeviceIDs": bind("clGetDeviceIDs",
            cl_int, cl_platform_id, cl_device_type,
            cl_uint, ctypes.POINTER(cl_device_id),
            ctypes.POINTER(cl_uint)),
        "clGetPlatformInfo": bind("clGetPlatformInfo",
            cl_int, cl_platform_id, cl_uint, size_t,
            void_p, ctypes.POINTER(size_t)),
        "clGetDeviceInfo": bind("clGetDeviceInfo",
            cl_int, cl_device_id, cl_uint, size_t,
            void_p, ctypes.POINTER(size_t)),
        "clCreateContext": bind("clCreateContext",
            cl_context, void_p, cl_uint,
            ctypes.POINTER(cl_device_id),
            void_p, void_p, ctypes.POINTER(cl_int)),
        "clCreateCommandQueue": bind("clCreateCommandQueue",
            cl_command_queue, cl_context, cl_device_id,
            ctypes.c_uint64, ctypes.POINTER(cl_int)),
        "clCreateProgramWithSource": bind("clCreateProgramWithSource",
            cl_program, cl_context, cl_uint,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(size_t),
            ctypes.POINTER(cl_int)),
        "clBuildProgram": bind("clBuildProgram",
            cl_int, cl_program, cl_uint,
            ctypes.POINTER(cl_device_id),
            ctypes.c_char_p, void_p, void_p),
        "clGetProgramBuildInfo": bind("clGetProgramBuildInfo",
            cl_int, cl_program, cl_device_id,
            cl_uint, size_t, void_p,
            ctypes.POINTER(size_t)),
        "clCreateKernel": bind("clCreateKernel",
            cl_kernel, cl_program, ctypes.c_char_p,
            ctypes.POINTER(cl_int)),
        "clCreateBuffer": bind("clCreateBuffer",
            cl_mem, cl_context, ctypes.c_uint64,
            size_t, void_p, ctypes.POINTER(cl_int)),
        "clEnqueueWriteBuffer": bind("clEnqueueWriteBuffer",
            cl_int, cl_command_queue, cl_mem,
            cl_uint, size_t, size_t,
            void_p, cl_uint, void_p, void_p),
        "clEnqueueReadBuffer": bind("clEnqueueReadBuffer",
            cl_int, cl_command_queue, cl_mem,
            cl_uint, size_t, size_t,
            void_p, cl_uint, void_p, void_p),
        "clSetKernelArg": bind("clSetKernelArg",
            cl_int, cl_kernel, cl_uint, size_t, void_p),
        "clEnqueueNDRangeKernel": bind("clEnqueueNDRangeKernel",
            cl_int, cl_command_queue, cl_kernel,
            cl_uint,
            ctypes.POINTER(size_t),
            ctypes.POINTER(size_t),
            ctypes.POINTER(size_t),
            cl_uint, void_p, void_p),
        "clFinish": bind("clFinish", cl_int, cl_command_queue),
        "clReleaseMemObject": bind("clReleaseMemObject", cl_int, cl_mem),
        "clReleaseKernel": bind("clReleaseKernel", cl_int, cl_kernel),
        "clReleaseProgram": bind("clReleaseProgram", cl_int, cl_program),
        "clReleaseCommandQueue": bind("clReleaseCommandQueue",
            cl_int, cl_command_queue),
        "clReleaseContext": bind("clReleaseContext", cl_int, cl_context),
    }
