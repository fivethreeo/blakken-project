"""
URL configuration for Meny project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from .views import auth, delete_page, dish_detail, dish_list, index, job_results, menu_pages, move_dish, move_page, page_visibility
from .orders import OrderAuthenticationForm, create_order, customer_order_auth, customer_orders, order_list, orders_page, order_status, shop_status

urlpatterns = [
    path('_nested_admin/', include('nested_admin.urls')),
    path('admin/', admin.site.urls),
    path('internal/auth/', auth, name='auth'),
    path('internal/order-auth/', customer_order_auth, name='customer-order-auth'),
    path('jobs/results/', job_results, name='job-results'),
    path('shop/status/', shop_status, name='shop-status'),
    path('orders/', orders_page, name='orders'),
    path('orders/login/', LoginView.as_view(
        template_name='orders_login.html', authentication_form=OrderAuthenticationForm,
        next_page='orders',
    ), name='orders-login'),
    path('orders/logout/', LogoutView.as_view(next_page='orders-login'), name='orders-logout'),
    path('orders/data/', order_list, name='order-list'),
    path('orders/mine/', customer_orders, name='customer-orders'),
    path('orders/<int:order_id>/status/', order_status, name='order-status'),
    path('menus/<int:menu_id>/orders/', create_order, name='create-order'),
    path('menus/<int:menu_id>/pages/', menu_pages, name='menu-pages'),
    path('menus/<int:menu_id>/dishes/<int:dish_id>/', dish_detail, name='dish-detail'),
    path('menus/<int:menu_id>/pages/<int:page_id>/dishes/', dish_list, name='dish-list'),
    path('menus/<int:menu_id>/pages/<int:page_id>/move/', move_page, name='move-page'),
    path('menus/<int:menu_id>/pages/<int:page_id>/visibility/', page_visibility, name='page-visibility'),
    path('menus/<int:menu_id>/pages/<int:page_id>/', delete_page, name='delete-page'),
    path('menus/<int:menu_id>/dishes/<int:dish_id>/move/', move_dish, name='move-dish'),
    path('', index, name='index'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
