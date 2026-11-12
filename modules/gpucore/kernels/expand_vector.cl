// expand_vector.cl — CORRECT 32-byte PBKDF2-HMAC-SHA1 (WPA2 PMK)
// Each work-item handles one candidate; produces 32-byte state.
// Two PBKDF2 blocks (counter=1 and counter=2) are required.

#define ROL32(x,n) (((x) << (n)) | ((x) >> (32-(n))))

__constant uint KD[4] = {0x5A827999u,0x6ED9EBA1u,0x8F1BBCDCu,0xCA62C1D6u};

inline void sha1_init(uint s[5])
{
    s[0]=0x67452301u; s[1]=0xEFCDAB89u; s[2]=0x98BADCFEu;
    s[3]=0x10325476u; s[4]=0xC3D2E1F0u;
}

inline void sha1_fold(uint s[5], __private const uchar *blk)
{
    uint w[80];
    for (int i = 0; i < 16; i++)
        w[i] = ((uint)blk[i*4]<<24)|((uint)blk[i*4+1]<<16)|
               ((uint)blk[i*4+2]<<8)|((uint)blk[i*4+3]);
    for (int i = 16; i < 80; i++)
        w[i] = ROL32(w[i-3]^w[i-8]^w[i-14]^w[i-16],1);
    uint a=s[0],b=s[1],c=s[2],d=s[3],e=s[4];
    for (int i = 0; i < 80; i++) {
        uint f,k;
        if (i<20){f=(b&c)|((~b)&d); k=KD[0];}
        else if (i<40){f=b^c^d; k=KD[1];}
        else if (i<60){f=(b&c)|(b&d)|(c&d); k=KD[2];}
        else {f=b^c^d; k=KD[3];}
        uint t=ROL32(a,5)+f+e+k+w[i];
        e=d;d=c;c=ROL32(b,30);b=a;a=t;
    }
    s[0]+=a;s[1]+=b;s[2]+=c;s[3]+=d;s[4]+=e;
}

inline void sha1_buf(__private const uchar *in, int mlen, __private uchar *out20)
{
    uchar buf[128];
    for (int i=0;i<mlen;i++) buf[i]=in[i];
    int tot=mlen; buf[tot++]=0x80;
    while (tot%64!=56) buf[tot++]=0;
    ulong bits=(ulong)mlen*8;
    for (int i=0;i<8;i++) buf[tot++]=(uchar)(bits>>(56-8*i));
    uint s[5]; sha1_init(s);
    for (int off=0; off<tot; off+=64) sha1_fold(s, buf+off);
    for (int i=0;i<20;i++) out20[i]=(uchar)(s[i/4]>>(24-8*(i%4)));
}

inline void hmac_sha1(__private const uchar *key, int klen,
                      __private const uchar *msg, int mlen,
                      __private uchar *out20)
{
    uchar k0[64];
    for (int i=0;i<64;i++) k0[i]=0;
    for (int i=0;i<klen && i<64;i++) k0[i]=key[i];

    uchar ipad[128], opad[128];
    for (int i=0;i<64;i++) { ipad[i]=k0[i]^0x36; opad[i]=k0[i]^0x5c; }
    for (int i=0;i<mlen;i++) ipad[64+i]=msg[i];
    uchar inner20[20];
    sha1_buf(ipad, 64+mlen, inner20);
    for (int i=0;i<20;i++) opad[64+i]=inner20[i];
    sha1_buf(opad, 64+20, out20);
}

// One PBKDF2 block (20 bytes) for a given counter (1 or 2)
inline void pbkdf2_block(__private const uchar *key, int klen,
                         __private const uchar *basis, int basis_len,
                         int counter, int rounds,
                         __private uchar *out20)
{
    uchar msg[80];
    int mlen = basis_len + 4;
    for (int i = 0; i < basis_len; i++) msg[i] = basis[i];
    msg[basis_len+0] = 0;
    msg[basis_len+1] = 0;
    msg[basis_len+2] = 0;
    msg[basis_len+3] = (uchar)counter;

    uchar U[20], Un[20];
    hmac_sha1(key, klen, msg, mlen, U);
    for (int i=0;i<20;i++) out20[i]=U[i];

    for (int r=1; r<rounds; r++) {
        hmac_sha1(key, klen, U, 20, Un);
        for (int i=0;i<20;i++) { out20[i]^=Un[i]; U[i]=Un[i]; }
    }
}

__kernel void expand_vector(
    __global const uchar *scalar_input,
    __global const int *input_lens,
    __global const uchar *basis,
    const int basis_len,
    const int max_len,
    const int rounds,
    __global uchar *state_out)
{
    int gid = get_global_id(0);
    __private uchar key[64];
    int klen = input_lens[gid];
    if (klen > 64) klen = 64;
    for (int i = 0; i < klen; i++) key[i] = scalar_input[gid*max_len + i];

    __private uchar basis_local[64];
    int blen = basis_len;
    if (blen > 64) blen = 64;
    for (int i = 0; i < blen; i++) basis_local[i] = basis[i];

    // Block 1 → bytes 0..19
    uchar block1[20];
    pbkdf2_block(key, klen, basis_local, blen, 1, rounds, block1);

    // Block 2 → bytes 20..31 (only first 12 bytes needed)
    uchar block2[20];
    pbkdf2_block(key, klen, basis_local, blen, 2, rounds, block2);

    for (int i=0;i<20;i++) state_out[gid*32+i] = block1[i];
    for (int i=0;i<12;i++) state_out[gid*32+20+i] = block2[i];
}
