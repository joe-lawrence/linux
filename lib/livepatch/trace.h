/* SPDX-License-Identifier: GPL-2.0 */
#undef TRACE_SYSTEM
#define TRACE_SYSTEM klp

#if !defined(_TRACE_TEST_KLP_STATIC_KEYS_H) || defined(TRACE_HEADER_MULTI_READ)
#define _TRACE_TEST_KLP_STATIC_KEYS_H

#include <linux/tracepoint.h>

TRACE_EVENT(test_klp_static_keys,

	TP_PROTO(const char *msg),
	TP_ARGS(msg),

	TP_STRUCT__entry(
		__string(msg, msg)
	),

	TP_fast_assign(
		__assign_str(msg, msg);
	),

	TP_printk("msg=\"%s\"", __get_str(msg))
);

#endif /* _TRACE_TEST_KLP_STATIC_KEYS_H */

/* This part must be outside protection */
#undef TRACE_INCLUDE_PATH
#undef TRACE_INCLUDE_FILE

#define TRACE_INCLUDE_PATH .
#define TRACE_INCLUDE_FILE trace

#include <trace/define_trace.h>
