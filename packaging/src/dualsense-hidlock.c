/*
 * dualsense-hidlock - narrowly-scoped privileged helper for the Bluetooth
 * HID proxy feature (see ../../bt_hid_proxy.py). Installed with
 * cap_fowner,cap_dac_override+ep (see ../dualsense-haptics.install) so the
 * unprivileged desktop app can hide the real DualSense's device nodes from
 * other processes (Steam included) while a virtual clone stands in for it,
 * and still open the real nodes itself despite that - without needing a
 * setuid-root binary or an interactive pkexec/sudo prompt on every toggle.
 *
 * Two modes, dispatched on argv[1]:
 *
 *   dualsense-hidlock <mode-octal> <path> [<path> ...]
 *     chmod every path to <mode-octal>. Used both to hide the real device's
 *     nodes (0600) and to restore their original mode afterwards.
 *
 *   dualsense-hidlock open-fd <path> <fd-number>
 *     Opens <path> O_RDWR (bypassing DAC via cap_dac_override - needed once
 *     72-dualsense-haptics-proxy-lock.rules has already locked the node to
 *     root:root before this process ever gets a chance to open it the
 *     ordinary way) and sends the resulting fd, via SCM_RIGHTS, over the
 *     already-open UNIX socket at file descriptor <fd-number> (inherited
 *     from the caller across exec - see bt_hid_proxy.py's use of
 *     subprocess.Popen(..., pass_fds=...)). Lets the caller use the real
 *     device without ever being able to open it via its own, unprivileged
 *     open() call - the node's DAC permissions can stay root:root
 *     permanently, with no window where an unprivileged peer (Steam runs as
 *     the same OS user as this app, so no ordinary permission bits could
 *     ever tell the two apart) could open it instead.
 *
 * In both modes, every path is resolved with realpath(3) FIRST (closing a
 * symlink-swap TOCTOU trick), then the resolved path must exactly match a
 * hidraw or input-event/js/mouse device node, then cross-checked against
 * sysfs that it genuinely belongs to a Sony DualSense/Edge - only then is it
 * touched. Never touches ownership (no CAP_CHOWN requested or needed), never
 * invokes a shell. Chmod failures are per-path, not all-or-nothing: prints
 * "OK <path>" or "SKIP <path>: <reason>" per line, exits 0 if every path
 * succeeded, 1 if some were skipped (so hiding 5 of 6 nodes isn't treated as
 * total failure by the caller); open-fd exits 0 only if the fd was both
 * opened and sent. 2 for a usage/argument error in either mode (no action
 * taken at all).
 */
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <regex.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
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

/* realpath(3) + path_shape_ok() + vendor/product cross-check, the exact same
 * validation both modes need before touching a path. Returns 1 and fills
 * `resolved` (a PATH_MAX buffer) on success; on failure returns 0 and writes
 * a human-readable reason into `reason` (a buffer of at least 64 bytes). */
static int resolve_and_validate(const char *raw, char *resolved, char *reason) {
    if (!realpath(raw, resolved)) {
        snprintf(reason, 64, "realpath failed");
        return 0;
    }
    int is_hidraw = 0;
    if (!path_shape_ok(resolved, &is_hidraw)) {
        snprintf(reason, 64, "not a recognized hidraw/input device path");
        return 0;
    }
    int belongs = is_hidraw ? hidraw_is_dualsense(resolved) : input_node_is_dualsense(resolved);
    if (!belongs) {
        snprintf(reason, 64, "not a Sony DualSense/Edge device");
        return 0;
    }
    return 1;
}

/* Opens `path` (already validated) O_RDWR - relying on cap_dac_override to
 * bypass DAC if the caller doesn't otherwise have permission - and sends the
 * resulting fd over `sock_fd` via SCM_RIGHTS. `sock_fd` is a UNIX socket the
 * caller (bt_hid_proxy.py) created and passed through exec specifically for
 * this one handoff; a single dummy byte of ordinary payload accompanies the
 * ancillary data since some implementations don't deliver a zero-length
 * SCM_RIGHTS message reliably. Returns 0 on success, matching main()'s exit
 * code convention. */
static int send_fd_for_path(const char *resolved, int sock_fd) {
    int real_fd = open(resolved, O_RDWR);
    if (real_fd < 0) {
        fprintf(stderr, "open %s failed: %s\n", resolved, strerror(errno));
        return 1;
    }

    struct iovec iov = {.iov_base = (void *)"F", .iov_len = 1};
    union {
        char buf[CMSG_SPACE(sizeof(int))];
        struct cmsghdr align;
    } control;
    struct msghdr msg = {0};
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = control.buf;
    msg.msg_controllen = sizeof(control.buf);

    struct cmsghdr *cmsg = CMSG_FIRSTHDR(&msg);
    cmsg->cmsg_level = SOL_SOCKET;
    cmsg->cmsg_type = SCM_RIGHTS;
    cmsg->cmsg_len = CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(cmsg), &real_fd, sizeof(int));

    int ok = sendmsg(sock_fd, &msg, 0) >= 0;
    if (!ok) fprintf(stderr, "sendmsg failed: %s\n", strerror(errno));
    close(real_fd); /* the receiving end now owns its own dup via SCM_RIGHTS */
    return ok ? 0 : 1;
}

static int run_open_fd(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s open-fd <path> <fd-number>\n", argv[0]);
        return 2;
    }
    char *end = NULL;
    long sock_fd = strtol(argv[3], &end, 10);
    if (end == argv[3] || *end != '\0' || sock_fd < 0 || sock_fd > INT_MAX) {
        fprintf(stderr, "invalid fd number: %s\n", argv[3]);
        return 2;
    }

    char resolved[PATH_MAX], reason[64];
    if (!resolve_and_validate(argv[2], resolved, reason)) {
        fprintf(stderr, "%s: %s\n", argv[2], reason);
        return 1;
    }
    return send_fd_for_path(resolved, (int)sock_fd);
}

#define MARKER_DIR "/run/dualsense-haptics"
#define MARKER_PATH MARKER_DIR "/lock-real-device"

/* Creates or removes the marker file 72-dualsense-haptics-proxy-lock.rules
 * watches (see ../72-dualsense-haptics-proxy-lock.rules): its mere presence
 * is what tells that rule to lock the real DualSense down the instant it
 * next appears, so this needs cap_dac_override too - /run is root:root
 * 0755, the caller here is not. No DualSense-specific validation applies:
 * unlike chmod/open-fd, this never touches a device node at all. */
static int run_mark(int argc, char **argv) {
    if (argc != 3 || (strcmp(argv[2], "on") != 0 && strcmp(argv[2], "off") != 0)) {
        fprintf(stderr, "usage: %s mark on|off\n", argv[0]);
        return 2;
    }
    if (strcmp(argv[2], "off") == 0) {
        if (unlink(MARKER_PATH) != 0 && errno != ENOENT) {
            fprintf(stderr, "remove %s failed: %s\n", MARKER_PATH, strerror(errno));
            return 1;
        }
        return 0;
    }
    if (mkdir(MARKER_DIR, 0755) != 0 && errno != EEXIST) {
        fprintf(stderr, "mkdir %s failed: %s\n", MARKER_DIR, strerror(errno));
        return 1;
    }
    int fd = open(MARKER_PATH, O_WRONLY | O_CREAT, 0644);
    if (fd < 0) {
        fprintf(stderr, "create %s failed: %s\n", MARKER_PATH, strerror(errno));
        return 1;
    }
    close(fd);
    return 0;
}

static int run_chmod(int argc, char **argv) {
    char *end = NULL;
    long mode = strtol(argv[1], &end, 8);
    if (end == argv[1] || *end != '\0' || mode < 0 || (mode & ~0777L) != 0) {
        fprintf(stderr, "invalid mode: %s\n", argv[1]);
        return 2;
    }

    int any_skipped = 0;
    for (int i = 2; i < argc; i++) {
        char resolved[PATH_MAX], reason[64];
        if (!resolve_and_validate(argv[i], resolved, reason)) {
            printf("SKIP %s: %s\n", argv[i], reason);
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

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "open-fd") == 0) {
        return run_open_fd(argc, argv);
    }
    if (argc >= 2 && strcmp(argv[1], "mark") == 0) {
        return run_mark(argc, argv);
    }
    if (argc < 3) {
        fprintf(stderr, "usage: %s <mode-octal> <path> [<path> ...]\n", argv[0]);
        fprintf(stderr, "       %s open-fd <path> <fd-number>\n", argv[0]);
        fprintf(stderr, "       %s mark on|off\n", argv[0]);
        return 2;
    }
    return run_chmod(argc, argv);
}
