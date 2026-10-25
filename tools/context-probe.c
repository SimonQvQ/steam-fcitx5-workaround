/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include <gtk/gtk.h>
#include <stdio.h>

int main(int argc, char **argv) {
    gtk_init(&argc, &argv);
    GtkIMContext *context = gtk_im_multicontext_new();
    char *text = NULL;
    PangoAttrList *attributes = NULL;
    int cursor = 0;
    gtk_im_context_get_preedit_string(context, &text, &attributes, &cursor);
    g_free(text);
    if (attributes) pango_attr_list_unref(attributes);
    GType type = g_type_from_name("FcitxIMContext");
    const char *sync = g_getenv("FCITX_ENABLE_SYNC_MODE");
    printf("Context: %s; Fcitx type registered: %s; synchronous: %s\n",
           gtk_im_multicontext_get_context_id(GTK_IM_MULTICONTEXT(context)),
           type ? "yes" : "no", sync ? sync : "(unset)");
    g_object_unref(context);
    return type && sync && g_strcmp0(sync, "1") == 0 ? 0 : 1;
}
