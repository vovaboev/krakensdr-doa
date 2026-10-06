import com.google.protobuf.gradle.id

plugins {
	kotlin("jvm") version "1.9.25"
	kotlin("plugin.spring") version "1.9.25"
	id("org.springframework.boot") version "3.3.4"
	id("io.spring.dependency-management") version "1.1.6"
	id("com.vaadin") version "24.5.0"
	id("com.google.protobuf")
	id("maven-publish")
}

group = "com.kraken"
version = "0.0.3"

java {
	toolchain {
		languageVersion = JavaLanguageVersion.of(17)
	}
}

repositories {
	mavenCentral()
}

extra["vaadinVersion"] = "24.5.0"

dependencies {
	implementation("org.springframework.boot:spring-boot-starter-web")
	implementation("com.fasterxml.jackson.module:jackson-module-kotlin")
	implementation("com.vaadin:vaadin-spring-boot-starter")
	implementation("org.jetbrains.kotlin:kotlin-reflect")
	testImplementation("org.springframework.boot:spring-boot-starter-test")
	testImplementation("org.jetbrains.kotlin:kotlin-test-junit5")
	testRuntimeOnly("org.junit.platform:junit-platform-launcher")
	implementation("io.grpc:grpc-kotlin-stub:1.4.0")
	implementation("io.grpc:grpc-protobuf:${property("grpcProtobufVersion")}")
	implementation("com.google.protobuf:protobuf-kotlin:${property("protobufKotlinVersion")}")
	implementation("io.grpc:grpc-api:1.68.0")
	implementation("io.grpc:grpc-okhttp:1.68.0")
	implementation("io.grpc:grpc-netty-shaded:1.68.0")
	implementation("io.grpc:grpc-stub:1.68.0")
	runtimeOnly("io.grpc:grpc-services:1.68.0")
	implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.3.2")
	implementation("org.parttio:canvas-java:2.0.0")
}

dependencyManagement {
	imports {
		mavenBom("com.vaadin:vaadin-bom:${property("vaadinVersion")}")
	}
}

kotlin {
	compilerOptions {
		freeCompilerArgs.addAll("-Xjsr305=strict")
	}
}

tasks.withType<Test> {
	useJUnitPlatform()
}

protobuf {
	protoc {
		artifact = "com.google.protobuf:protoc:${property("protobufKotlinVersion")}"
	}
	plugins {
		id("grpc") {
			artifact = "io.grpc:protoc-gen-grpc-java:${property("grpcProtobufVersion")}"
		}
		id("grpckt") {
			artifact = "io.grpc:protoc-gen-grpc-kotlin:${property("grpcKotlinVersion")}:jdk8@jar"
		}
	}
	generateProtoTasks {
		all().forEach {
			it.plugins {
				id("grpc")
				id("grpckt")
			}
			it.builtins {
				id("kotlin")
			}
		}
	}
}

sourceSets {
	main {
		proto {
			srcDir("../proto")
		}
	}
}

vaadin {
	productionMode = true
}