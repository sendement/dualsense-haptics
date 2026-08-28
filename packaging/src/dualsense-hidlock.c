/*
 * dualsense-hidlock - narrowly-scoped chmod helper for the Bluetooth HID
 * proxy feature (see ../../bt_hid_proxy.py). Installed with cap_fowner+ep
 * (see ../dualsense-haptics.install) so the unprivileged desktop app can hide
 * the real DualSense's device nodes from other processes (Steam included)
 * while a virtual clone stands in for it, and restore them afterwards -
 * without needing a setuid-root binary or an interactive pkexec/sudo prompt
 * on every toggle.
 *
 * Usage: dualsense-hidlock <mode-octal> <path> [<path> ...]
 *
 * Every path is resolved with realpath(3) FIRST (closing a symlink-swap
 * TOCTOU trick), then the resolved path must exactly match a hidraw or
 * input-event/js/mouse device node, then cross-checked against sysfs that it
 * genuinely belongs to a Sony DualSense/Edge - only then is it chmod'd.
 * Never touches ownership (no CAP_CHOWN requested or needed), never invokes
 * a shell. Failures are per-path, not all-or-nothing: prints "OK <path>" or
 * "SKIP <path>: <reason>" per line, exits 0 if every path succeeded, 1 if
 * some were skipped (so hiding 5 of 6 nodes isn't treated as total failure
 * by the caller), 2 for a usage/argument error (no action taken at all).
 */
#include <limits.h>
#include <regex.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define SONY_VENDOR 0x054cu
static const unsigned product_ids[] = {0x0ce6u, 0x0df2u}; /* DualSense, DualSense Edge */

static int is_allowed_product(unsigned pid) {
    for (size_t i = 0; i < sizeof(product_ids) / sizeof(product_ids[0]); i++) {
        if (product_ids[i] == pid) return 1;
    }
    return 0;
}

/* Reads "KEY=value" lines from a small sysfs text file, calling `cb` for
 * each. Used for both hidraw's uevent (HID_ID=bus:vendor:product) and input
 * devices' id/vendor + id/product (plain hex, no prefix). */
static int read_line_matches(const char *path, const char *prefix, char *out, size_t out_len) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char line[256];
    int found = 0;
    size_t prefix_len = strlen(prefix);
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, prefix, prefix_len) == 0) {
            size_t n = strcspn(line + prefix_len, "\n");
            if (n >= out_len) n = out_len - 1;
            memcpy(out, line + prefix_len, n);
            out[n] = '\0';
            found = 1;
            break;
        }
    }
    fclose(f);
    return found;
}

/* /dev/hidrawN -> /sys/class/hidraw/hidrawN/device/uevent's HID_ID=bus:vendor:product */
static int hidraw_is_dualsense(const char *resolved) {
    const char *base = strrchr(resolved, '/');
    base = base ? base + 1 : resolved;
    char sys_path[PATH_MAX];
    snprintf(sys_path, sizeof(sys_path), "/sys/class/hidraw/%s/device/uevent", base);
    char value[64];
    if (!read_line_matches(sys_path, "HID_ID=", value, sizeof(value))) return 0;
    unsigned bus, vendor, product;
    if (sscanf(value, "%x:%x:%x", &bus, &vendor, &product) != 3) return 0;
    return vendor == SONY_VENDOR && is_allowed_product(product);
}

/* /dev/input/eventN|jsN|mouseN -> walk up to its /sys/class/input/eventN/device
 * (the input handler's own parent input device node) and read id/vendor,
 * id/product from there. */
static int input_node_is_dualsense(const char *resolved) {
    const char *base = strrchr(resolved, '/');
    base = base ? base + 1 : resolved;
    char vendor_path[PATH_MAX], product_path[PATH_MAX];
    snprintf(vendor_path, sizeof(vendor_path), "/sys/class/input/%s/device/id/vendor", base);
    snprintf(product_path, sizeof(product_path), "/sys/class/input/%s/device/id/product", base);
    char vbuf[16], pbuf[16];
    FILE *vf = fopen(vendor_path, "r");
    FILE *pf = fopen(product_path, "r");
    int ok = 0;
    if (vf && pf && fgets(vbuf, sizeof(vbuf), vf) && fgets(pbuf, sizeof(pbuf), pf)) {
        unsigned vendor = (unsigned)strtoul(vbuf, NULL, 16);
        unsigned product = (unsigned)strtoul(pbuf, NULL, 16);
        ok = vendor == SONY_VENDOR && is_allowed_product(product);
    }
    if (vf) fclose(vf);
    if (pf) fclose(pf);
    return ok;
}

static int path_shape_ok(const char *resolved, int *is_hidraw) {
    static regex_t hidraw_re, input_re;
    static int compiled = 0;
    if (!compiled) {
        regcomp(&hidraw_re, "^/dev/hidraw[0-9]+$", REG_EXTENDED | REG_NOSUB);
        regcomp(&input_re, "^/dev/input/(event|js|mouse)[0-9]+$", REG_EXTENDED | REG_NOSUB);
        compiled = 1;
    }
    if (regexec(&hidraw_re, resolved, 0, NULL, 0) == 0) {
        *is_hidraw = 1;
        return 1;
    }
    if (regexec(&input_re, resolved, 0, NULL, 0) == 0) {
        *is_hidraw = 0;
        return 1;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <mode-octal> <path> [<path> ...]\n", argv[0]);
        return 2;
    }

    char *end = NULL;
    long mode = strtol(argv[1], &end, 8);
    if (end == argv[1] || *end != '\0' || mode < 0 || (mode & ~0777L) != 0) {
        fprintf(stderr, "invalid mode: %s\n", argv[1]);
        return 2;
    }

    int any_skipped = 0;
    for (int i = 2; i < argc; i++) {
        char resolved[PATH_MAX];
        if (!realpath(argv[i], resolved)) {
            printf("SKIP %s: realpath failed\n", argv[i]);
            any_skipped = 1;
            continue;
        }

        int is_hidraw = 0;
        if (!path_shape_ok(resolved, &is_hidraw)) {
            printf("SKIP %s: not a recognized hidraw/input device path\n", resolved);
            any_skipped = 1;
            continue;
        }

        int belongs = is_hidraw ? hidraw_is_dualsense(resolved) : input_node_is_dualsense(resolved);
        if (!belongs) {
            printf("SKIP %s: not a Sony DualSense/Edge device\n", resolved);
            any_skipped = 1;
            continue;
        }

        if (chmod(resolved, (mode_t)mode) != 0) {
            printf("SKIP %s: chmod failed\n", resolved);
            any_skipped = 1;
            continue;
        }

        printf("OK %s\n", resolved);
    }

    return any_skipped ? 1 : 0;
}
