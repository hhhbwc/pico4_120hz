#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <errno.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s module.ko [flags_hex]\n", argv[0]);
        return 1;
    }
    int flags = argc > 2
        ? (int)strtol(argv[2], NULL, 16)
        : 0x0;
    int fd = open(argv[1], O_RDONLY);
    if (fd < 0) { perror("open"); return 1; }
    long rc = syscall(SYS_finit_module, fd, "", flags);
    int err = errno;
    close(fd);
    printf("finit_module rc=%ld errno=%d (%s)\n", rc, err, strerror(err));
    return rc < 0 ? 1 : 0;
}
