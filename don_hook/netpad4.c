/* Experimental D.O.N input barrier. Generated payloads are local game artifacts.
 * Hashes here cover agreed INPUTS ONLY; simulation determinism is not certified.
 * This build is for the single-PC loopback test, not production netplay.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define RING 128u
#define MAGIC 0x34504e44u
enum { IDLE, CAPTURED, WAITING, APPLYING, STOPPED };
typedef struct { u8 raw[24]; volatile u32 tag; u32 aux; } Entry;
typedef struct { volatile u32 tag; u32 value; } Hash;
typedef struct {
    u32 magic, version, size;
    volatile u32 active, abort, hold, status, local_slot;
    volatile u32 frame, captures, stalls, missing, hash_kind;
    u32 players; /* host driver metadata: 2..4 humans; hardware always has four sockets */
    u32 reserved[2];
    Entry out[RING];
    Entry in[4][RING];
    Hash hash[RING];
} Shared;

volatile Shared g_np4 = { .magic=MAGIC, .version=1, .size=sizeof(Shared), .hash_kind=1 };
static u8 latched[4][32];
extern int np4_read_original(int port, int slot, void *data);

static void commit(void) {
#ifdef __mips__
    __asm__ volatile("sync" ::: "memory");
#else
    __sync_synchronize();
#endif
}

/* Separated from game calls so the compiled engine can also be tested natively. */
int np4_exchange(const u8 *raw) {
    volatile Shared *s = &g_np4;
    u32 frame = s->frame, tag = frame+1, index = frame & (RING-1);
    u32 slot, i, missing, h = 2166136261u;
    if (frame == 0xffffffffu) { s->abort=1; return 0; }
    for (i=0; i<24; ++i) s->out[index].raw[i] = raw[i];
    s->out[index].aux = frame;
    commit();
    s->out[index].tag = tag;
    s->captures = tag;
    s->status = CAPTURED;
    do {
        missing = 0;
        for (slot=0; slot<4; ++slot)
            if (s->in[slot][index].tag != tag) missing |= 1u<<slot;
        s->missing = missing;
        if (!s->active || s->abort) { s->status=STOPPED; return 0; }
        if (missing || s->hold) { s->status=WAITING; s->stalls++; }
    } while (missing || s->hold);
    s->status = APPLYING;
    for (slot=0; slot<4; ++slot) {
        for (i=0; i<24; ++i) {
            u8 value = s->in[slot][index].raw[i];
            latched[slot][i] = value;
            h = (h ^ value)*16777619u;
        }
        for (i=24; i<32; ++i) latched[slot][i]=0;
    }
    s->hash[index].value = h;
    commit();
    s->hash[index].tag = tag;
    return 1;
}

int np4_read(int port, int slot, void *data) {
    unsigned int i;
    u8 *dest = data;
    if (!g_np4.active || g_np4.abort || port != 0 || (unsigned int)slot >= 4)
        return np4_read_original(port, slot, data);
    for (i=0; i<32; ++i) dest[i] = latched[slot][i];
    return 32;
}

void np4_poll(void *records, void *summary) {
    void (*original)(void *, void *) = (void *)0x138fb0;
    u8 raw[128] __attribute__((aligned(16)));
    u32 i;
    if (!g_np4.active || g_np4.abort) {
        original(records, summary);
        return;
    }
    for (i=0; i<128; ++i) raw[i]=0;
    /* Every PC's physical pad 1A supplies its Django-assigned network slot. */
    if (np4_read_original(0, 0, raw) < 8 || raw[0] != 0) {
        g_np4.abort=1;
        g_np4.status=STOPPED;
        original(records, summary);
        return;
    }
    if (!np4_exchange(raw)) {
        *(volatile u32 *)0x4d6a08 = 1;
        original(records, summary);
        return;
    }
    /* The ordinary game loop copies and clears this pending-VBlank value.
     * A network stall must not become a variable number of simulation ticks.
     */
    *(volatile u32 *)0x4d6a08 = 1;
    original(records, summary);
    *(volatile u32 *)0x4d6a08 = 1;
    g_np4.frame++;
    g_np4.status=IDLE;
}
