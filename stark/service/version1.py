import functools
from types import FunctionType

from django import forms
from django.db.models import Q
from django.db.models import ForeignKey, ManyToManyField
from django.http import QueryDict
from django.urls import re_path
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.shortcuts import HttpResponse, render, redirect

from stark.utils.pagination import Pagination


class StarkModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(StarkModelForm, self).__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'


def get_choice_text(title, field):
    """
    对于Stark组件中定义列时，choice如果想要显示中文信息，调用此方法即可
    :param title: 希望页面显示的表头
    :param field: 字段名称
    :return:
    """

    def wrapper(self, obj=None, is_header=None):
        if is_header:
            return title
        method = 'get_%s_display' % field
        return getattr(obj, method)()

    return wrapper


class Option(object):
    def __init__(self, field, db_condition=None):
        """

        :param field: 组合搜索关联的字段
        :param db_condition: 数据库关联查询时的条件
        """

        self.field = field
        if not db_condition:
            db_condition = {}
        self.db_condition = db_condition

    def get_db_condition(self, request, *args, **kwargs):  # 为了日后扩展
        return self.db_condition

    def get_queryset_or_tuple(self, model_class, request, *args, **kwargs):
        """
        根据字段获取关联数据
        :return:
        """

        # 根据gender或depart字符串，去自己对应的Model类中找到字段对象
        field_obj = model_class._meta.get_field(self.field)

        # 获取关联数据
        if isinstance(field_obj, ForeignKey) or isinstance(field_obj, ManyToManyField):
            # FK和M2M，应该获取其关联的表中的数据
            db_condition = self.get_db_condition(request, *args, **kwargs)
            print(self.field, field_obj.related_model.objects.filter(**db_condition))

            # print(field, field_obj.related_model) # django2.x用这个
            # print(field,field_obj.rel.model)  # django 1.x用这个

        else:
            # 获取choice中的数据
            print(self.field, field_obj.choices)


class StarkSite:
    def __init__(self):
        self._registry = []
        self.app_name = 'stark'
        self.namespace = 'stark'

    def register(self, model_class, handler_class=None, prev=None):
        """
        :param model_class: 是models中的数据库表对应的类。models.UserInfo
        :param handler_class: 处理请求的视图函数所在的类
        :param prev: 生成URL的前缀
        :return:
        """
        if not handler_class:
            handler_class = StarkHandler
        self._registry.append(
            {'model_class': model_class, 'handler': handler_class(self, model_class, prev), 'prev': prev})

        """
        self._registry = [
            {'prev':'None',model_class': model.Department,'handler':DepartmentHandler(models.Department,prev)对象中有一个model_class=models.Department},
            {'prev':'private','model_class': model.UserInfo,'handler':UserInfo(models.UserInfo,prev)对象中有一个model_class=models.UserInfo}, 
            {'prev':'None','model_class': model.Host,'handler':Host(models.Host,prev)对象中有一个model_class=models.Host},
        ]
        """

    def get_urls(self):
        patterns = []
        for item in self._registry:
            model_class = item['model_class']
            handler = item['handler']  # 实例化了StarkHandler，hanlder是StarkHandler的对象
            prev = item['prev']
            app_name = model_class._meta.app_label  # 获取当前类所在的app名称
            model_name = model_class._meta.model_name  # 获取当前类所在的表名称

            if prev:
                patterns.append(
                    re_path(r'^%s/%s/%s/' % (app_name, model_name, prev,), (handler.get_urls(), None, None))
                )
            else:
                patterns.append(
                    re_path(r'^%s/%s/' % (app_name, model_name,), (handler.get_urls(), None, None))
                )

        return patterns

    @property
    def urls(self):
        return self.get_urls(), self.app_name, self.namespace


class StarkHandler:
    list_display = []
    per_page_count = 10
    has_add_btn = True
    model_form_class = None
    order_list = []
    search_list = []
    action_list = []

    search_group = []

    def __init__(self, site, model_class, prev):
        self.site = site
        self.model_class = model_class
        self.prev = prev
        self.request = None

    def get_search_group(self):
        return self.search_group

    def get_action_list(self):
        return self.action_list

    def action_multi_delete(self, request, *args, **kwargs):
        """
        批量删除（如果想要定制执行成功后的返回值，那么久为action函数设置返回值）
        :param request:
        :return:
        """
        pk_list = request.POST.getlist('pk')  # checkbox的name都叫pk
        self.model_class.objects.filter(id__in=pk_list).delete()

        return redirect('https://www.baidu.com')

    action_multi_delete.text = '批量删除'

    def get_search_list(self):
        return self.search_list

    def get_order_list(self):
        return self.order_list or ['-id', ]

    def get_add_btn(self):
        if self.has_add_btn:
            return f'<a href="%s" class="btn btn-primary">添加</a>' % self.reverse_add_url()
        return None

    def get_model_form_class(self):
        if self.model_form_class:
            return self.model_form_class

        class DynamicModelForm(StarkModelForm):
            class Meta:
                model = self.model_class
                fields = '__all__'

        return DynamicModelForm

    def save(self, form, is_update=False):
        """
        在使用ModelForm保存数据之前预留的钩子方法
        :param form:
        :param is_update:
        :return:
        """
        form.save()

    def display_checkbox(self, obj=None, is_header=None):
        """
        自定义显示的列
        :param obj:
        :param is_header:
        :return:
        """
        if is_header:
            return '选择'
        return mark_safe('<input type="checkbox" name="pk" value="%s"/>' % obj.pk)

    def display_edit(self, obj=None, is_header=None):
        """
        自定义页面显示的列（表头和内容）
        :param obj:
        :param is_header:
        :return:
        """
        if is_header:
            return '编辑表头'
        return mark_safe('<a href="%s">编辑</a>' % self.reverse_edit_url(pk=obj.pk))

    def display_del(self, obj=None, is_header=None):
        if is_header:
            return '删除表头'
        return mark_safe('<a href="%s">删除</a>' % self.reverse_delete_url(pk=obj.pk))

    def get_list_display(self):
        """
        获取页面上应该显示的列,自定义扩展，列如：根据用户的不同来显示不同的列
        :return:
        """
        values = []
        values.extend(self.list_display)

        return values

    def list_view(self, request, *args, **kwargs):
        """
        列表页面
        :param request:
        :return:
        """

        # 1. 处理action
        action_list = self.get_action_list()
        action_dict = {func.__name__: func.text for func in action_list}
        # 往模板传函数，模板会自动执行,所以要用这个方式，而且后台也需要获取函数名，然后通过反射执行这个函数。
        # {'multi_delete':'批量删除', 'multi_init':'批量初始化'}

        if request.method == 'POST':
            action_func_name = request.POST.get('action')
            # 不能为空（用户必须选择了复选框），而且函数名必须在定义的字典里，防止用户在前端传入其他函数名对网站造成破坏。
            if action_func_name and action_func_name in action_dict:
                action_response = getattr(self, action_func_name)(request, *args, **kwargs)
                if action_response:  # 如果有返回值就返回返回值，不往下走了。 例如： redirect('https://www.taobao.com)
                    return action_response

                    # 2. 处理搜索

        search_list = self.get_search_list()
        search_value = request.GET.get('q', '')
        conn = Q()
        conn.connector = 'OR'
        if search_value:
            for item in search_list:
                conn.children.append((item, search_value))

        # 3. 获取排序

        order_list = self.get_order_list()
        queryset = self.model_class.objects.filter(conn).order_by(*order_list)

        # 4.处理分页
        all_count = queryset.count()
        query_params = request.GET.copy()  # page=1&level=2
        # query_params._mutable = True  # 把_mutable变成True，才可以被修改page
        # query_params['page'] = 2
        pager = Pagination(
            current_page=request.GET.get('page'),
            all_count=all_count,
            base_url=request.path_info,
            query_params=query_params,
            per_page_data=self.per_page_count,
        )

        data_list = queryset[pager.start:pager.end]

        list_display = self.get_list_display()

        # 5. 处理表格的表头
        # 访问http://127.0.0.1:8000/stark/app01/userinfo/list
        # 页面上要显示的列，示例：['name', 'age', 'email']

        header_list = []
        if list_display:
            for field_or_func in list_display:  # self.model_class._meta.get_field()拿到的是数据库里的一个字段
                if isinstance(field_or_func, FunctionType):
                    verbose_name = field_or_func(self, obj=None, is_header=True)
                    header_list.append(verbose_name)
                else:
                    verbose_name = self.model_class._meta.get_field(field_or_func).verbose_name
                    header_list.append(verbose_name)
        else:
            header_list.append(self.model_class._meta.model_name)  # 没有定义list_display，让表头显示表名称

        # 6. 处理表的内容 ['name','age']

        body_list = []
        for queryset_obj in data_list:
            tr_list = []
            if list_display:
                for field_or_func in list_display:
                    if isinstance(field_or_func, FunctionType):
                        # field_or_func是函数（类调用的），所以要传递self
                        tr_list.append(field_or_func(self, queryset_obj, is_header=False))
                    else:
                        tr_list.append(getattr(queryset_obj, field_or_func))  # obj.depart
            else:
                tr_list.append(queryset_obj)
            body_list.append(tr_list)

        # 7.处理添加按钮
        add_btn = self.get_add_btn()

        # 8. 处理组合搜索
        search_group = self.get_search_group()  # ['gender','depart']
        for option_object in search_group:
            option_object.get_queryset_or_tuple(self.model_class, request, *args, **kwargs)
            # 传request,*args,**kwargs是为了处理用户通过url传过来的参数
        context = {
            'data_list': data_list,
            'header_list': header_list,
            'body_list': body_list,
            'pager': pager,
            'add_btn': add_btn,
            'search_list': search_list,
            'search_value': search_value,
            'action_dict': action_dict,
            'search_group': search_group,
        }

        return render(request, 'stark/data_list.html', context)

    def add_view(self, request, *args, **kwargs):
        """
        添加页面
        :param request:
        :return:
        """

        model_form_class = self.get_model_form_class()
        if request.method == 'GET':
            form = model_form_class
            return render(request, 'stark/change.html', {'form': form})

        form = model_form_class(data=request.POST)
        if form.is_valid():
            self.save(form, is_update=False)
            # 在数据库保存成功后，跳回列表页面（携带原来的参数）
            return redirect(self.reverse_list_url())

        return render(request, 'stark/change.html', {'form': form})

    def edit_view(self, request, pk, *args, **kwargs):
        """
        编辑页面
        :param request:
        :param pk:
        :return:
        """

        current_edit_obj = self.model_class.objects.filter(pk=pk).first()

        if not current_edit_obj:
            return HttpResponse('要修改的数据不存在，请重新选择')
        model_form_class = self.get_model_form_class()
        if request.method == 'GET':
            form = model_form_class(instance=current_edit_obj)
            return render(request, 'stark/change.html', {'form': form})
        form = model_form_class(data=request.POST, instance=current_edit_obj)
        if form.is_valid():
            self.save(form, is_update=False)
            return redirect(self.reverse_list_url())
        return render(request, 'stark/change.html', {'form': form})

    def delete_view(self, request, pk, *args, **kwargs):
        """
        删除页面
        :param request:
        :param pk:
        :return:
        """

        list_url = self.reverse_list_url()
        if request.method == 'GET':
            return render(request, 'stark/delete.html', {'cancel': list_url})
        self.model_class.objects.filter(pk=pk).delete()

        return redirect(list_url)

    def get_url_name(self, crud):
        app_name, model_name = self.model_class._meta.app_label, self.model_class._meta.model_name
        if self.prev:
            return "%s_%s_%s_%s" % (app_name, model_name, self.prev, crud)
        return "%s_%s_%s" % (app_name, model_name, crud)

    @property
    def get_list_url_name(self):
        """
        获取列表页面URL的name
        :return:
        """
        return self.get_url_name('list')

    @property
    def get_add_url_name(self):
        """
        获取添加页面URL的name
        :return:
        """
        return self.get_url_name('add')

    @property
    def get_edit_url_name(self):
        """
        获取修改页面URL的name
        :return:
        """
        return self.get_url_name('edit')

    @property
    def get_delete_url_name(self):
        """
        获取删除页面URL的name
        :return:
        """
        return self.get_url_name('delete')

    def reverse_add_url(self):
        """
        生成带有原搜索条件的添加URL
        :return:
        """
        name = '%s:%s' % (self.site.namespace, self.get_add_url_name)
        base_url = reverse(name)
        if not self.request.GET:
            add_url = base_url
        else:
            params = self.request.GET.urlencode()
            new_query_dict = QueryDict(mutable=True)
            new_query_dict['_filter'] = params
            add_url = '%s?%s' % (base_url, new_query_dict.urlencode())
        return add_url

    def reverse_edit_url(self, *args, **kwargs):
        """
         生成带有原搜索条件的编辑URL
        :param args:
        :param kwargs:
        :return:
        """
        name = '%s:%s' % (self.site.namespace, self.get_edit_url_name)
        base_url = reverse(name, args=args, kwargs=kwargs)
        if not self.request.GET:
            edit_url = base_url
        else:
            params = self.request.GET.urlencode()
            new_query_dict = QueryDict(mutable=True)
            new_query_dict['_filter'] = params
            edit_url = '%s?%s' % (base_url, new_query_dict.urlencode())
        return edit_url

    def reverse_delete_url(self, *args, **kwargs):
        """
         生成带有原搜索条件的删除URL
        :param args:
        :param kwargs:
        :return:
        """
        name = '%s:%s' % (self.site.namespace, self.get_delete_url_name)
        base_url = reverse(name, args=args, kwargs=kwargs)
        if not self.request.GET:
            delete_url = base_url
        else:
            params = self.request.GET.urlencode()
            new_query_dict = QueryDict(mutable=True)
            new_query_dict['_filter'] = params
            delete_url = "%s?%s" % (base_url, new_query_dict.urlencode())
        return delete_url

    def reverse_list_url(self):
        """
        跳转回列表页面时，生成的URL
        :return:
        """
        name = '%s:%s' % (self.site.namespace, self.get_list_url_name)
        basic_url = reverse(name)
        params = self.request.GET.get('_filter')
        if not params:
            return basic_url
        return '%s?%s' % (basic_url, params)

    def wrapper(self, func):  # 增删改查视图函数的时候，给self.request赋值request
        @functools.wraps(func)  # 保留原函数的原信息，写装饰器建议写上这个。
        def inner(request, *args, **kwargs):
            self.request = request
            return func(request, *args, **kwargs)

        return inner

    def get_urls(self):  # 先在传进来的handler里重写
        patterns = [
            re_path(r'^list/$', self.wrapper(self.list_view), name=self.get_list_url_name),
            re_path(r'^add/$', self.wrapper(self.add_view), name=self.get_add_url_name),
            re_path(r'^edit/(?P<pk>\d+)/$', self.wrapper(self.edit_view), name=self.get_edit_url_name),
            re_path(r'^delete/(?P<pk>\d+)/$', self.wrapper(self.delete_view), name=self.get_delete_url_name),
        ]
        patterns.extend(self.extra_urls())  # 先去传进来的handler里找
        return patterns

    def extra_urls(self):
        return []


site = StarkSite()
