/* Encode one YUV420P frame from official.avi and compare scan size. */
#include "atj_avi_scan.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int read_file(const char *path, uint8_t **out, size_t *out_len)
{
    FILE *f = fopen(path, "rb");
    long n;
    uint8_t *buf;

    if (!f)
        return -1;
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return -1;
    }
    n = ftell(f);
    if (n <= 0) {
        fclose(f);
        return -1;
    }
    rewind(f);
    buf = malloc((size_t)n);
    if (!buf) {
        fclose(f);
        return -1;
    }
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) {
        free(buf);
        fclose(f);
        return -1;
    }
    fclose(f);
    *out = buf;
    *out_len = (size_t)n;
    return 0;
}

int main(int argc, char **argv)
{
    const char *yuv_path = "/tmp/atj_avi_f0.yuv";
    int quality = 14;
    uint8_t *yuv = NULL;
    size_t yuv_len = 0;
    uint8_t out[256 * 1024];
    AtjAviScanEnc *enc;
    int n;

    if (argc > 1)
        yuv_path = argv[1];
    if (argc > 2)
        quality = atoi(argv[2]);

    if (read_file(yuv_path, &yuv, &yuv_len) != 0) {
        fprintf(stderr, "read %s failed (run: djpeg -crop 128x128+0+0 -grayscale off /tmp/atj_avi_f0.jpg | ...)\n",
                yuv_path);
        fprintf(stderr, "  or extract YUV: ffmpeg -i official.avi -frames:v 1 -pix_fmt yuv420p %s\n", yuv_path);
        return 1;
    }
    if (yuv_len < 128 * 128 * 3 / 2) {
        fprintf(stderr, "yuv too small: %zu\n", yuv_len);
        free(yuv);
        return 1;
    }

    enc = atj_avi_scan_enc_open(128, 128, quality);
    if (!enc) {
        fprintf(stderr, "atj_avi_scan_enc_open failed\n");
        free(yuv);
        return 1;
    }

    n = atj_avi_scan_enc_frame(enc, yuv, out, sizeof(out));
    atj_avi_scan_enc_close(enc);
    free(yuv);

    if (n < 0) {
        fprintf(stderr, "encode failed: %d\n", n);
        return 1;
    }

    printf("vendor_q=%d ijg_q=%d total=%d scan=%d\n",
           quality, atj_avi_scan_vendor_to_ijg_quality(quality), n, n - 623);
    {
        FILE *jf = fopen("/tmp/atj_avi_scan_test.jpg", "wb");
        if (!jf || fwrite(out, 1, (size_t)n, jf) != (size_t)n) {
            fprintf(stderr, "write /tmp/atj_avi_scan_test.jpg failed\n");
            if (jf)
                fclose(jf);
            return 1;
        }
        fclose(jf);
        printf("wrote /tmp/atj_avi_scan_test.jpg\n");
    }
    return 0;
}
