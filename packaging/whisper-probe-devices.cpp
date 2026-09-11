// SPDX-License-Identifier: MIT
// Model-independent enumeration using the exact linked ggml backends.
#include "ggml-backend.h"
#include <cstdio>
#include <exception>
static void json_string(const char *s) {
 std::putchar('"');
 for(const unsigned char *p=(const unsigned char *)s;*p;p++) {
  if(*p=='"'||*p=='\\') {std::putchar('\\');std::putchar(*p);}
  else if(*p<0x20) std::printf("\\u%04x",*p);
  else std::putchar(*p);
 }
 std::putchar('"');
}
int main() {
 try {
  ggml_backend_load_all();
  std::printf("{\"devices\":[");
  int gpu_index=0;
  for(size_t i=0;i<ggml_backend_dev_count();i++) {
   ggml_backend_dev_t d=ggml_backend_dev_get(i);
   auto type=ggml_backend_dev_type(d);
   bool gpu=type==GGML_BACKEND_DEVICE_TYPE_GPU||type==GGML_BACKEND_DEVICE_TYPE_IGPU;
   std::printf("%s{\"index\":%zu,\"gpu_index\":",i?",":"",i);
   if(gpu) std::printf("%d",gpu_index++); else std::printf("null");
   std::printf(",\"name\":");json_string(ggml_backend_dev_name(d));
   std::printf(",\"description\":");json_string(ggml_backend_dev_description(d));
   std::printf(",\"type\":%d,\"is_gpu\":%s}",(int)type,gpu?"true":"false");
  }
  std::puts("],\"inference_verified\":false}");return 0;
 }catch(const std::exception &e){std::fprintf(stderr,"device probe failed: %s\n",e.what());return 1;}
}
