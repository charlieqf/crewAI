import ctypes
import os
import logging
import platform

logger = logging.getLogger(__name__)

# Define C structs
class Slice_t(ctypes.Structure):
    _fields_ = [
        ("buf", ctypes.c_char_p),
        ("len", ctypes.c_int),
    ]

class MediaData_t(ctypes.Structure):
    _fields_ = [
        ("outindexbuf", ctypes.c_char_p),
        ("out_len", ctypes.c_int),
        ("data", ctypes.c_char_p),
        ("data_len", ctypes.c_int),
        ("is_finish", ctypes.c_int),
    ]

class WeWorkFinanceSDK:
    """Python wrapper for libWeWorkFinanceSdk_C.so using ctypes."""

    def __init__(self, lib_path: str = None):
        if lib_path is None:
            # Default to location in company_docs
            lib_path = os.getenv("WECOM_FINANCE_SDK_LIB", "/opt/wecom-callback/company_docs/C_sdk/libWeWorkFinanceSdk_C.so")
        
        if not os.path.exists(lib_path):
            raise FileNotFoundError(f"WeCom Finance SDK library not found at: {lib_path}")

        try:
            self.lib = ctypes.CDLL(lib_path)
            self._setup_functions()
            self.sdk = None
            logger.info(f"Successfully loaded WeCom Finance SDK from {lib_path}")
        except Exception as e:
            logger.error(f"Failed to load WeCom Finance SDK: {e}")
            raise

    def _setup_functions(self):
        # void* NewSdk()
        self.lib.NewSdk.restype = ctypes.c_void_p
        self.lib.NewSdk.argtypes = []

        # int Init(void* sdk, const char* corpid, const char* secret)
        self.lib.Init.restype = ctypes.c_int
        self.lib.Init.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]

        # int GetChatData(void* sdk, unsigned long long seq, unsigned int limit, const char* proxy, const char* passwd, int timeout, Slice_t* chatData)
        self.lib.GetChatData.restype = ctypes.c_int
        self.lib.GetChatData.argtypes = [
            ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_uint, 
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, 
            ctypes.c_void_p # Slice_t*
        ]

        # int DecryptData(const char* encrypt_key, const char* encrypt_msg, Slice_t* msg)
        self.lib.DecryptData.restype = ctypes.c_int
        self.lib.DecryptData.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p]

        # int GetMediaData(void* sdk, const char* indexbuf, const char* sdkFileid, const char* proxy, const char* passwd, int timeout, MediaData_t* mediaData)
        self.lib.GetMediaData.restype = ctypes.c_int
        self.lib.GetMediaData.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
            ctypes.c_void_p # MediaData_t*
        ]

        # void DestroySdk(void* sdk)
        self.lib.DestroySdk.restype = None
        self.lib.DestroySdk.argtypes = [ctypes.c_void_p]

        # Slice_t* NewSlice()
        self.lib.NewSlice.restype = ctypes.c_void_p
        self.lib.NewSlice.argtypes = []

        # void FreeSlice(Slice_t* slice)
        self.lib.FreeSlice.restype = None
        self.lib.FreeSlice.argtypes = [ctypes.c_void_p]

        # char* GetContentFromSlice(Slice_t* slice)
        self.lib.GetContentFromSlice.restype = ctypes.c_char_p
        self.lib.GetContentFromSlice.argtypes = [ctypes.c_void_p]

        # int GetSliceLen(Slice_t* slice)
        self.lib.GetSliceLen.restype = ctypes.c_int
        self.lib.GetSliceLen.argtypes = [ctypes.c_void_p]

        # MediaData_t* NewMediaData()
        self.lib.NewMediaData.restype = ctypes.c_void_p
        self.lib.NewMediaData.argtypes = []

        # void FreeMediaData(MediaData_t* media_data)
        self.lib.FreeMediaData.restype = None
        self.lib.FreeMediaData.argtypes = [ctypes.c_void_p]

        # char* GetOutIndexBuf(MediaData_t* media_data)
        self.lib.GetOutIndexBuf.restype = ctypes.c_char_p
        self.lib.GetOutIndexBuf.argtypes = [ctypes.c_void_p]

        # char* GetData(MediaData_t* media_data) - MUST use c_void_p to avoid null truncation
        self.lib.GetData.restype = ctypes.c_void_p
        self.lib.GetData.argtypes = [ctypes.c_void_p]

        # int GetIndexLen(MediaData_t* media_data)
        self.lib.GetIndexLen.restype = ctypes.c_int
        self.lib.GetIndexLen.argtypes = [ctypes.c_void_p]

        # int GetDataLen(MediaData_t* media_data)
        self.lib.GetDataLen.restype = ctypes.c_int
        self.lib.GetDataLen.argtypes = [ctypes.c_void_p]

        # int IsMediaDataFinish(MediaData_t* media_data)
        self.lib.IsMediaDataFinish.restype = ctypes.c_int
        self.lib.IsMediaDataFinish.argtypes = [ctypes.c_void_p]

    def init(self, corp_id: str, secret: str) -> bool:
        """Initialize the SDK with credentials."""
        self.sdk = self.lib.NewSdk()
        if not self.sdk:
            logger.error("Failed to create SDK instance")
            return False
        
        ret = self.lib.Init(self.sdk, corp_id.encode(), secret.encode())
        if ret != 0:
            logger.error(f"Failed to initialize SDK with CorpID/Secret: ret={ret}")
            return False
        
        return True

    def decrypt_data(self, encrypt_key: str, encrypt_msg: str) -> str:
        """Decrypt chat message data using the provided (decrypted) random key."""
        slice_out = self.lib.NewSlice()
        if not slice_out:
            logger.error("Failed to allocate Slice for decryption")
            return None
            
        try:
            ret = self.lib.DecryptData(encrypt_key.encode(), encrypt_msg.encode(), slice_out)
            if ret != 0:
                logger.error(f"Failed to decrypt message data: ret={ret}")
                return None
            
            content = self.lib.GetContentFromSlice(slice_out)
            length = self.lib.GetSliceLen(slice_out)
            if content and length > 0:
                return content[:length].decode('utf-8')
            return None
        finally:
            self.lib.FreeSlice(slice_out)

    def get_chat_data(self, seq: int, limit: int = 100, timeout: int = 30) -> list[dict]:
        """Fetch chat messages starting from seq+1."""
        if not self.sdk:
            raise RuntimeError("SDK not initialized. Call init() first.")
            
        slice_out = self.lib.NewSlice()
        if not slice_out:
            logger.error("Failed to allocate Slice for GetChatData")
            return None
            
        import json
        try:
            ret = self.lib.GetChatData(
                self.sdk, seq, limit, 
                None, None, timeout, slice_out
            )
            
            if ret != 0:
                logger.error(f"Failed to get chat data: ret={ret}")
                return None
                
            content = self.lib.GetContentFromSlice(slice_out)
            length = self.lib.GetSliceLen(slice_out)
            if content and length > 0:
                raw_data = content[:length].decode('utf-8')
                data = json.loads(raw_data)
                return data.get("chatdata", [])
            return []
        except Exception as e:
            logger.error(f"Failed to parse chat data JSON: {e}")
            return None
        finally:
            self.lib.FreeSlice(slice_out)

    def get_media_data(self, sdk_file_id: str, timeout: int = 30) -> bytes:
        """Download complete media data (file content) using sdk_file_id."""
        if not self.sdk:
            raise RuntimeError("SDK not initialized. Call init() first.")

        index_buf = b""
        full_data = b""
        
        while True:
            media_out = self.lib.NewMediaData()
            if not media_out:
                logger.error("Failed to allocate MediaData for GetMediaData")
                break
                
            try:
                ret = self.lib.GetMediaData(
                    self.sdk, index_buf, sdk_file_id.encode(), 
                    None, None, timeout, media_out
                )
                
                if ret != 0:
                    logger.error(f"Failed to get media data for {sdk_file_id}: ret={ret}")
                    break
                    
                data_ptr = self.lib.GetData(media_out)
                data_len = self.lib.GetDataLen(media_out)
                if data_ptr and data_len > 0:
                    # Use string_at to get binary data without null truncation
                    full_data += ctypes.string_at(data_ptr, data_len)
                
                next_index_ptr = self.lib.GetOutIndexBuf(media_out)
                next_index_len = self.lib.GetIndexLen(media_out)
                if next_index_ptr and next_index_len > 0:
                    index_buf = next_index_ptr[:next_index_len]
                else:
                    index_buf = b""
                    
                is_finish = self.lib.IsMediaDataFinish(media_out)
                if is_finish:
                    break
            finally:
                self.lib.FreeMediaData(media_out)
        
        return full_data

    def __del__(self):
        if hasattr(self, 'sdk') and self.sdk:
            try:
                self.lib.DestroySdk(self.sdk)
                self.sdk = None
            except:
                pass
