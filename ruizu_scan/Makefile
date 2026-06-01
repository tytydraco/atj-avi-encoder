ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -fPIC
LIBS ?= -lturbojpeg
BUILD := $(ROOT)build

.PHONY: all clean

all: $(BUILD)/libruizu_scan.so $(BUILD)/ruizu_scan_test

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/ruizu_scan_enc.o: ruizu_scan_enc.c ruizu_scan.h ruizu_tables.h ruizu_header.h | $(BUILD)
	$(CC) $(CFLAGS) -c ruizu_scan_enc.c -o $@

$(BUILD)/libruizu_scan.so: $(BUILD)/ruizu_scan_enc.o
	$(CC) $(CFLAGS) -shared -o $@ $^ $(LIBS)

$(BUILD)/ruizu_scan_test: ruizu_scan_test.c $(BUILD)/ruizu_scan_enc.o
	$(CC) $(CFLAGS) -o $@ ruizu_scan_test.c $(BUILD)/ruizu_scan_enc.o $(LIBS)

clean:
	rm -rf $(BUILD)
