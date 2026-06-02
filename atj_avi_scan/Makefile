ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -fPIC
LIBS ?= -lturbojpeg
BUILD := $(ROOT)build

.PHONY: all clean

all: $(BUILD)/libatj_avi_scan.so $(BUILD)/atj_avi_scan_test

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/atj_avi_scan_enc.o: atj_avi_scan_enc.c atj_avi_scan.h atj_avi_tables.h atj_avi_header.h | $(BUILD)
	$(CC) $(CFLAGS) -c atj_avi_scan_enc.c -o $@

$(BUILD)/libatj_avi_scan.so: $(BUILD)/atj_avi_scan_enc.o
	$(CC) $(CFLAGS) -shared -o $@ $^ $(LIBS)

$(BUILD)/atj_avi_scan_test: atj_avi_scan_test.c $(BUILD)/atj_avi_scan_enc.o
	$(CC) $(CFLAGS) -o $@ atj_avi_scan_test.c $(BUILD)/atj_avi_scan_enc.o $(LIBS)

clean:
	rm -rf $(BUILD)
