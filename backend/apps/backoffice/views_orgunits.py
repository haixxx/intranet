from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from apps.organization.models import OrgUnit
from apps.organization.forms import OrgUnitForm
from apps.audit.utils import audit_log

@login_required
@permission_required('organization.view_orgunit', raise_exception=True)
def orgunit_list(request):
    q = request.GET.get('q', '').strip()
    type_filter = request.GET.get('type', '').strip()
    parent_filter = request.GET.get('parent', '').strip()

    # Pagination params
    page = request.GET.get('page', '1')
    page_size_raw = request.GET.get('page_size', '').strip()
    try:
        page_size = int(page_size_raw) if page_size_raw else 25
    except ValueError:
        page_size = 25
    if page_size <= 0 or page_size > 500:
        page_size = 25

    qs = OrgUnit.objects.select_related('parent').all()

    if type_filter:
        qs = qs.filter(type=type_filter)
    if parent_filter:
        qs = qs.filter(parent_id=parent_filter)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(symbol__icontains=q))

    qs = qs.order_by('type', 'symbol')

    paginator = Paginator(qs, page_size)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # Lựa chọn type và parent cho filter
    type_choices = list(OrgUnit.Type.choices)
    parents = OrgUnit.objects.exclude(type='TEAM').order_by('symbol')  # đơn vị không phải Tổ

    return render(request, 'backoffice/org/units/list.html', {
        'units': page_obj.object_list,
        'query': q,
        'type_selected': type_filter,
        'parent_selected': parent_filter,
        'type_choices': type_choices,
        'parents': parents,
        'paginator': paginator,
        'page_obj': page_obj,
        'current_page': page_obj.number,
        'page_size': page_size,
        'total_count': paginator.count,
        'page_size_options': [25, 50, 100, 200],
    })

@login_required
@permission_required('organization.add_orgunit', raise_exception=True)
def orgunit_create(request):
    if request.method == 'POST':
        form = OrgUnitForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            # generate code OU0001...
            from django.db.models import Max
            max_code = OrgUnit.objects.aggregate(m=Max('code'))['m']
            next_num = (int(max_code[2:]) + 1) if (max_code and max_code.startswith('OU')) else 1
            obj.code = f"OU{next_num:04d}"
            obj.full_clean()
            obj.save()
            audit_log(action_verb="CREATE", object_type="orgunit", object_id=obj.id, object_repr=obj.symbol,
                      actor=request.user, changes={'fields': {'symbol': obj.symbol, 'name': obj.name, 'type': obj.type}},
                      request=request, action_code="ORGUNIT_CREATE")
            messages.success(request, "Đã tạo đơn vị.")
            return redirect('backoffice:orgunit_list')
    else:
        form = OrgUnitForm()
    return render(request, 'backoffice/org/units/form.html', {'form': form, 'create': True})

@login_required
@permission_required('organization.change_orgunit', raise_exception=True)
def orgunit_edit(request, pk):
    obj = get_object_or_404(OrgUnit, pk=pk)
    if request.method == 'POST':
        old = {'symbol': obj.symbol, 'name': obj.name, 'type': obj.type, 'parent': obj.parent_id}
        form = OrgUnitForm(request.POST, instance=obj)
        if form.is_valid():
            updated = form.save()
            diff = {}
            for k in old:
                newv = getattr(updated, k if k != 'parent' else 'parent_id')
                if old[k] != newv:
                    diff[k] = {'old': old[k], 'new': newv}
            if diff:
                audit_log(action_verb="UPDATE", object_type="orgunit", object_id=updated.id, object_repr=updated.symbol,
                          actor=request.user, changes=diff, request=request, action_code="ORGUNIT_UPDATE")
            messages.success(request, "Đã cập nhật đơn vị.")
            return redirect('backoffice:orgunit_list')
    else:
        form = OrgUnitForm(instance=obj)
    return render(request, 'backoffice/org/units/form.html', {'form': form, 'obj': obj})

@login_required
@permission_required('organization.delete_orgunit', raise_exception=True)
def orgunit_delete(request, pk):
    obj = get_object_or_404(OrgUnit, pk=pk)
    if request.method == 'POST':
        oid, sym = obj.id, obj.symbol
        obj.delete()
        audit_log(action_verb="DELETE", object_type="orgunit", object_id=oid, object_repr=sym,
                  actor=request.user, request=request, action_code="ORGUNIT_DELETE")
        messages.success(request, "Đã xóa đơn vị.")
        return redirect('backoffice:orgunit_list')
    return render(request, 'backoffice/org/units/confirm_delete.html', {'obj': obj})