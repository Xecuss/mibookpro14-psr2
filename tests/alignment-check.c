
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef uint16_t u16;
struct drm_dsc_config { int slice_height; };
struct intel_display {
    void *drm;
    struct { int psr2_su_y_alignment; } params;
    struct { bool alderlake_p; } platform;
    int version;
};
struct intel_crtc_state {
    struct intel_display *display;
    struct { struct drm_dsc_config config; bool compression_enable; } dsc;
    struct { struct { int crtc_vdisplay; } adjusted_mode; } hw;
    int su_y_granularity;
    struct { int y1, y2; } psr2_su_area;
};
#define to_intel_display(state) ((state)->display)
#define DISPLAY_VER(display) ((display)->version)
#define drm_info_once(...) ((void)0)
static bool intel_psr2_sel_fetch_pipe_alignment(struct intel_crtc_state *crtc_state)
{
	struct intel_display *display = to_intel_display(crtc_state);
	const struct drm_dsc_config *vdsc_cfg = &crtc_state->dsc.config;
	int requested = display->params.psr2_su_y_alignment;
	int height = crtc_state->hw.adjusted_mode.crtc_vdisplay;
	u16 y_alignment;
	bool su_area_changed = false;

	/* ADLP aligns the SU region to vdsc slice height in case dsc is enabled */
	if (crtc_state->dsc.compression_enable &&
	    (display->platform.alderlake_p || DISPLAY_VER(display) >= 14))
		y_alignment = vdsc_cfg->slice_height;
	else
		y_alignment = crtc_state->su_y_granularity;

	/*
	 * Experiment with a coarser grid while retaining selective update.
	 * Preserve the native sink/DSC alignment and require a whole number
	 * of bands so rounding up never crosses the bottom of the mode.
	 * This runs inside the ET alignment loop, before plane SF areas are
	 * derived, so newly intersected cursors and all planes are covered.
	 */
	if (requested) {
		if (y_alignment && requested >= y_alignment &&
		    requested <= height && requested % y_alignment == 0 &&
		    height % requested == 0)
			y_alignment = requested;
		else
			drm_info_once(display->drm,
				      "Ignoring PSR SU y alignment %d (native %u, height %d)\n",
				      requested, y_alignment, height);
	}

	if (crtc_state->psr2_su_area.y1 % y_alignment) {
		crtc_state->psr2_su_area.y1 -= crtc_state->psr2_su_area.y1 % y_alignment;
		su_area_changed = true;
	}

	if (crtc_state->psr2_su_area.y2 % y_alignment) {
		crtc_state->psr2_su_area.y2 = ((crtc_state->psr2_su_area.y2 /
						y_alignment) + 1) * y_alignment;
		su_area_changed = true;
	}

	return su_area_changed;
}

int main(void)
{
    const struct { int height, native, request, expected; bool dsc; } cases[] = {
        {2080,4,0,4,false}, {2080,4,104,104,false},
        {2080,4,103,4,false}, {2080,4,-1,4,false},
        {2080,4,70000,4,false}, {2160,4,104,4,false},
        {2080,130,104,130,true}, {2080,130,260,260,true},
        {2080,104,104,104,true}, {2080,4,2080,2080,false},
    };
    unsigned long checks=0;
    for (unsigned c=0;c<sizeof(cases)/sizeof(cases[0]);c++) {
        struct intel_display d={ .params.psr2_su_y_alignment=cases[c].request,
                                 .version=30 };
        struct intel_crtc_state s={ .display=&d, .su_y_granularity=cases[c].native,
            .dsc={.compression_enable=cases[c].dsc,
                  .config.slice_height=cases[c].native},
            .hw.adjusted_mode.crtc_vdisplay=cases[c].height };
        for (int y1=0;y1<cases[c].height;y1++)
            for (int y2=y1+1;y2<=cases[c].height;y2++) {
                s.psr2_su_area.y1=y1; s.psr2_su_area.y2=y2;
                bool changed=intel_psr2_sel_fetch_pipe_alignment(&s);
                int a=cases[c].expected;
                int expected1=y1/a*a, expected2=(y2+a-1)/a*a;
                if (s.psr2_su_area.y1!=expected1 || s.psr2_su_area.y2!=expected2 ||
                    s.psr2_su_area.y1>y1 || s.psr2_su_area.y2<y2 ||
                    s.psr2_su_area.y1<0 || s.psr2_su_area.y2>cases[c].height ||
                    s.psr2_su_area.y1%cases[c].native ||
                    s.psr2_su_area.y2%cases[c].native ||
                    changed!=(expected1!=y1 || expected2!=y2)) {
                    fprintf(stderr,"FAIL case %u [%d,%d)\n",c,y1,y2); return 1;
                }
                if (intel_psr2_sel_fetch_pipe_alignment(&s)) {
                    fprintf(stderr,"FAIL not idempotent case %u\n",c); return 1;
                }
                checks++;
            }
    }
    printf("PASS: %lu intervals across 10 configurations; coverage, native alignment, bounds, fallback and idempotence\n",checks);
    return 0;
}
