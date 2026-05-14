import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, FormView, ListView

from .forms import QueryDemoForm
from .models import Query

log = logging.getLogger("irri")


class QueryListView(LoginRequiredMixin, ListView):
    model = Query
    template_name = "queries/list.html"
    context_object_name = "queries"
    paginate_by = 25

    def get_queryset(self):
        qs = Query.objects.select_related("hook", "catalogue")
        g = self.request.GET
        if g.get("category"):
            qs = qs.filter(category=g["category"])
        if g.get("feedback"):
            qs = qs.filter(farmer_feedback=g["feedback"])
        if g.get("season"):
            qs = qs.filter(season=g["season"])
        if g.get("crop_stage"):
            qs = qs.filter(crop_stage=g["crop_stage"])
        if g.get("district"):
            qs = qs.filter(district__icontains=g["district"])
        if g.get("q"):
            qs = qs.filter(translated_query_text__icontains=g["q"])
        return qs.order_by("-timestamp")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Query.objects.all()
        ctx["total"] = qs.count()
        ctx["responded"] = qs.filter(status="Responded").count()
        ctx["pending"] = qs.filter(status__in=["Received", "Processing", "Failed"]).count()
        ctx["flagged"] = qs.filter(flagged_for_review=True).count()
        ctx["category_choices"] = Query.CATEGORY_CHOICES
        ctx["feedback_choices"] = Query.FEEDBACK_CHOICES
        ctx["season_choices"] = Query.SEASON_CHOICES
        ctx["crop_stage_choices"] = Query.CROP_STAGE_CHOICES
        return ctx


class QueryDetailView(LoginRequiredMixin, DetailView):
    model = Query
    template_name = "queries/detail.html"
    context_object_name = "qobj"


class QueryDemoView(LoginRequiredMixin, FormView):
    template_name = "queries/demo_form.html"
    form_class = QueryDemoForm

    def form_valid(self, form):
        from .services.pipeline import run_pipeline_for_image, run_pipeline_for_text

        image = form.cleaned_data.get("image")
        try:
            if image:
                query = run_pipeline_for_image(
                    catalogue=form.cleaned_data["catalogue"],
                    farmer_language=form.cleaned_data["farmer_language"],
                    uploaded_image=image,
                    district=form.cleaned_data["district"] or "",
                    generate_tts=form.cleaned_data["generate_tts"],
                    user_type=form.cleaned_data["user_type"],
                    user_query_text=form.cleaned_data.get("query_text") or "",
                )
            else:
                query = run_pipeline_for_text(
                    catalogue=form.cleaned_data["catalogue"],
                    farmer_language=form.cleaned_data["farmer_language"],
                    query_text=form.cleaned_data["query_text"],
                    district=form.cleaned_data["district"] or "",
                    generate_tts=form.cleaned_data["generate_tts"],
                    user_type=form.cleaned_data["user_type"],
                )
        except Exception as exc:
            log.exception("Demo pipeline failed")
            messages.error(self.request, f"Pipeline error: {exc}")
            return self.form_invalid(form)
        return redirect("queries:detail", pk=query.pk)


@login_required
@require_POST
def flag_query(request, pk):
    role = getattr(request.user, "role", None)
    if not role or role.name not in ("Administrator", "Reviewer"):
        return HttpResponseForbidden("Not permitted.")
    q = get_object_or_404(Query, pk=pk)
    q.flagged_for_review = not q.flagged_for_review
    q.status = "Flagged" if q.flagged_for_review else "Responded"
    q.reviewed_by = request.user
    q.save()
    messages.info(request, "Flag toggled.")
    return redirect("queries:detail", pk=pk)


@login_required
@require_POST
def set_feedback(request, pk):
    q = get_object_or_404(Query, pk=pk)
    fb = request.POST.get("feedback", "")
    if fb in {"Good", "Average", "Bad"}:
        q.farmer_feedback = fb
        q.save()
        messages.success(request, "Feedback saved.")
    return redirect("queries:detail", pk=pk)
